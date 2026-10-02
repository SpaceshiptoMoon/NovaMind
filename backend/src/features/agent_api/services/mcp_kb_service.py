"""MCP tool 编排服务（agent_api 批次 2）：目标解析 → SearchService → 输出组装。

kb_search / kb_ask 两个 MCP tool 的内核。复用 SearchService 公共面（R2）：
- 权限链完整继承（空间成员 + 文档级 hidden_doc_ids 过滤在服务内生效）；
- kb_ask 复用 SearchRequest.llm 的 answer 通道（`[Source N]` 引用格式，
  LLM 失败时 answer=None 但检索结果照常返回——降级不阻断）；
- MCP tool 错误是给 LLM 消费的字符串：域异常转友好文本，不走 BaseAPIError 管道。
"""
from __future__ import annotations

import json
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# snippet 截断（MCP 输出给 LLM 消费，300 字符足够上下文判断）
SNIPPET_LIMIT = 300


class McpKbService:
    """MCP 知识库 tool 编排服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def search(
        self,
        user_id: int,
        query: str,
        space_id: int | None = None,
        kb_id: int | None = None,
        top_k: int = 5,
        with_answer: bool = False,
    ) -> str:
        """检索（with_answer=True 时附带 LLM 引用回答），返回 JSON 文本给 LLM。

        Raises:
            ToolTextError: 目标解析失败/无权限等——消息已面向 LLM 友好。
        """
        from novamind.features.knowledge_space.schemas.search_schema import (
            SearchLLMConfig,
            SearchRequest,
        )
        from novamind.features.knowledge_space.services.search_service import SearchService
        from novamind.features.user.services.model_config_service import ModelConfigService

        space_id, kb_id = await self._resolve_target(user_id, space_id, kb_id)

        search_request = SearchRequest(
            query=query,
            top_k=top_k,
            llm=SearchLLMConfig(enabled=with_answer, temperature=0.3) if with_answer else None,
        )
        search_service = SearchService(
            session=self.session,
            es_client=await self._get_es_client(),
            model_config_service=ModelConfigService(self.session),
        )
        result = await search_service.search(
            space_id=space_id, kb_id=kb_id, user_id=user_id, request=search_request,
        )

        return self._format_output(result, with_answer=with_answer)

    # ========== 内部 ==========

    async def _resolve_target(
        self, user_id: int, space_id: int | None, kb_id: int | None,
    ) -> tuple[int, int]:
        """解析检索目标（space/kb 双可选）。

        - space_id 缺失：用户恰属一个空间则自动选定；否则列出候选让 agent 二次调用时指定；
        - kb_id 缺失：该空间下第一个 ACTIVE KB。

        Raises:
            ToolTextError: 面向 LLM 的目标解析失败说明。
        """
        from sqlalchemy import select

        from novamind.features.knowledge_space.models.knowledge_base import (
            KnowledgeBase,
            KnowledgeBaseStatus,
        )
        from novamind.features.knowledge_space.models.knowledge_space import (
            KnowledgeSpace,
        )

        if space_id is None:
            # 用户所属空间（成员表 join 空间表，只看未删空间）
            from novamind.features.knowledge_space.models.space_member import SpaceMember

            rows = (await self.session.execute(
                select(KnowledgeSpace.id, KnowledgeSpace.name)
                .join(SpaceMember, SpaceMember.space_id == KnowledgeSpace.id)
                .where(
                    SpaceMember.user_id == user_id,
                    KnowledgeSpace.deleted_at.is_(None),
                )
                .order_by(KnowledgeSpace.id)
            )).all()
            if not rows:
                raise ToolTextError("你尚未加入任何知识空间，无法检索。请先在 NovaMind 中加入空间。")
            if len(rows) > 1:
                candidates = "、".join(f"{r.id}({r.name})" for r in rows)
                raise ToolTextError(
                    f"你属于多个知识空间，请指定 space_id 参数。候选：{candidates}"
                )
            space_id = rows[0].id

        if kb_id is None:
            kb = (await self.session.execute(
                select(KnowledgeBase.id)
                .where(
                    KnowledgeBase.space_id == space_id,
                    KnowledgeBase.status == KnowledgeBaseStatus.ACTIVE,
                    KnowledgeBase.deleted_at.is_(None),
                )
                .order_by(KnowledgeBase.id)
                .limit(1)
            )).scalar_one_or_none()
            if kb is None:
                raise ToolTextError(f"空间 {space_id} 下没有可检索的知识库。")
            kb_id = kb

        return space_id, kb_id

    async def _get_es_client(self):
        from novamind.features.knowledge_space.api.dependencies import (
            get_elasticsearch_client,
        )

        return await get_elasticsearch_client()

    def _format_output(self, result: dict[str, Any], *, with_answer: bool) -> str:
        """组装 MCP 输出（JSON 文本）：snippet 序号与 answer 的 [Source N] 对齐。"""
        sources = result.get("results", [])
        formatted = []
        for i, r in enumerate(sources, start=1):
            formatted.append({
                "rank": i,
                "space_id": r.get("space_id"),
                "kb_id": r.get("kb_id"),
                "document_id": r.get("document_id"),
                "chunk_id": r.get("chunk_id"),
                "document_name": (r.get("file_info") or {}).get("filename"),
                "chunk_type": r.get("chunk_type"),
                "score": round(r["score"], 4) if r.get("score") is not None else None,
                "snippet": (r.get("content") or "")[:SNIPPET_LIMIT],
            })

        output: dict[str, Any] = {
            "total": len(formatted),
            "results": formatted,
        }
        if with_answer:
            answer = result.get("answer")
            output["answer"] = answer
            output["answer_model"] = result.get("answer_model")
            if answer is None:
                # LLM 失败降级：检索结果照常返回，附提示让 agent 自行综合
                output["answer_error"] = "回答生成失败，请基于 results 自行综合"
        return json.dumps(output, ensure_ascii=False, indent=2)


class ToolTextError(Exception):
    """面向 LLM 的 tool 错误（MCP 层转 ToolError；消息即给 LLM 的说明文本）。"""
