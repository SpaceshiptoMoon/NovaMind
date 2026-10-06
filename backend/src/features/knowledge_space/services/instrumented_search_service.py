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
from sqlalchemy.ext.asyncio import AsyncSession

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
    ) -> dict[str, Any]:
        """检索 + query 事件埋点。

        Args:
            space_id: 空间 ID。
            kb_id: 知识库 ID。
            user_id: 触发用户 ID。
            request: 检索请求参数。
            bypass_document_permission: 跳过文档级权限过滤（系统重放专用，
                用户路径不应传；仍埋点但 extra 标记，供账本侧甄别）。

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
    ) -> None:
        """记录 query 事件（旁路：全异常吞掉，账本挂了检索照常）。

        载荷口径：query_text 走 EventRecorder 脱敏；结果数/最高分/检索模式/
        耗时进 extra——零命中（results=0）与低分（max_score 低于阈值）是
        归因流水线的两类核心信号。
        """
        try:
            from novamind.features.knowledge_ops.services.event_recorder import (
                EventRecorder,
            )

            results = result.get("results") or []
            max_score = max((r.get("score") or 0) for r in results) if results else 0.0
            await EventRecorder().record(
                event_type="query",
                user_id=user_id,
                space_id=space_id,
                kb_id=kb_id,
                query_text=request.query,
                extra={
                    "results_count": len(results),
                    "max_score": round(max_score, 4),
                    "search_mode": str(
                        request.search_mode.value
                        if hasattr(request.search_mode, "value")
                        else request.search_mode
                    ),
                    "top_k": request.top_k,
                    "bypass_document_permission": bypass_document_permission,
                },
            )
        except Exception as e:
            logger.warning("检索 query 事件记录失败（已忽略）", error=str(e))
