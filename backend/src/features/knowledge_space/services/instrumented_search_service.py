"""带运营埋点的检索服务：SearchService 的用户行为观测包装。

在 search() 外围记录 query 事件到 kb-ops 事件账本（回路 A 消费信号的
总线级采集点）——所有用户触发的检索消费方（QA/Agent/MCP/检索页/
deep_research）换用本类后自动进账本，埋点不再依赖调用方自觉。
系统内部重放（kb-ops 归因 worker、evaluation 重放）不是用户行为，
继续直接用 SearchService，避免污染消费统计。
"""
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.schemas.search_schema import SearchRequest
from novamind.features.knowledge_space.services.search_service import SearchService

logger = get_logger(__name__)


class InstrumentedSearchService(SearchService):
    """检索 + 运营埋点：search() 前后旁路记录 query 事件，失败不拖垮检索。

    继承而非组合：调用方零改动面（构造签名与公开方法不变，替换 import
    即接入），检索行为完全由父类承载。
    """

    def __init__(self, *args, **kwargs):
        """透传父类构造；埋点经 EventRecorder 独立短事务（旁路语义）。"""
        super().__init__(*args, **kwargs)
        self.logger = get_logger(__name__)

    async def search(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        request: SearchRequest,
        *,
        bypass_document_permission: bool = False,
        user_role: str | None = None,
    ) -> dict[str, Any]:
        """检索 + query 事件埋点。

        Args:
            space_id: 空间 ID。
            kb_id: 知识库 ID。
            user_id: 触发用户 ID。
            request: 检索请求参数。
            bypass_document_permission: 跳过文档级权限过滤（系统重放专用，
                用户路径不应传；仍埋点但 extra 标记，供账本侧甄别）。
            user_role: 触发者角色标识（调用方鉴权上下文现成携带时透传，
                如 MCP key 归属人的 role_code；不查库，None 不写该字段）。

        Returns:
            父类检索结果字典（原样透传）。
        """
        result = await super().search(
            space_id, kb_id, user_id, request,
            bypass_document_permission=bypass_document_permission,
        )
        await self._record_query_event(
            space_id=space_id, kb_id=kb_id, user_id=user_id, request=request,
            result=result, bypass_document_permission=bypass_document_permission,
            user_role=user_role,
        )
        return result

    async def _record_query_event(
        self,
        *,
        space_id: int,
        kb_id: int,
        user_id: int,
        request: SearchRequest,
        result: dict[str, Any],
        bypass_document_permission: bool,
        user_role: str | None = None,
    ) -> None:
        """记录 query 事件（旁路：全异常吞掉，账本挂了检索照常）。

        载荷口径：query_text 走 EventRecorder 脱敏；结果数/最高分/检索模式/
        耗时进 extra——零命中（results=0）与低分（max_score 低于阈值）是
        归因流水线的两类核心信号；hits 承载每条命中明细（定位键 + 200 字符
        内容摘要），归因时免反查 ES 即可判断「为什么这条被召回」。
        """
        try:
            from novamind.features.knowledge_ops.services.event_recorder import (
                EventRecorder,
            )

            results = result.get("results") or []
            scores = [
                r.get("score") for r in results if isinstance(r.get("score"), (int, float))
            ]
            max_score = max(scores) if scores else 0.0
            extra: dict[str, Any] = {
                "results_count": len(results),
                "max_score": round(max_score, 4),
                "search_mode": str(
                    request.search_mode.value
                    if hasattr(request.search_mode, "value")
                    else request.search_mode
                ),
                "top_k": request.top_k,
                "bypass_document_permission": bypass_document_permission,
                "hits": [self._hit_payload(r) for r in results],
            }
            if user_role:
                extra["user_role"] = user_role
            await EventRecorder().record(
                event_type="query",
                user_id=user_id,
                space_id=space_id,
                kb_id=kb_id,
                query_text=request.query,
                extra=extra,
            )
        except Exception as e:
            logger.warning("检索 query 事件记录失败（已忽略）", error=str(e))

    @staticmethod
    def _hit_payload(r: dict[str, Any]) -> dict[str, Any]:
        """单条命中的埋点载荷：定位键 + 得分 + 文件名 + 内容前 200 字符摘要。

        摘要长度是埋点口径（归因可读即可），不是检索内容契约；字段全部
        get 兜底缺省——埋点不得因个别条目形状异常而中断（旁路语义）。
        """
        score = r.get("score")
        file_info = r.get("file_info") or {}
        content = r.get("content") or ""
        return {
            "document_id": r.get("document_id"),
            "chunk_id": r.get("chunk_id"),
            "score": round(score, 4) if isinstance(score, (int, float)) else None,
            "document_name": file_info.get("filename"),
            "snippet": content[:200],
        }
