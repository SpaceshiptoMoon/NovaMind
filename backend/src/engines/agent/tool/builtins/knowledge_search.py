"""
内置工具：知识库搜索，提供空间发现、知识库浏览、文档检索的完整工具链。
"""
import json
from typing import Any

from novamind.engines.agent.tool.base import BaseTool
from novamind.features.knowledge_space.schemas.search_schema import SearchMode
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class KnowledgeSearchTool(BaseTool):
    """知识库搜索工具"""

    @property
    def name(self) -> str:
        return "knowledge_search"

    @property
    def description(self) -> str:
        return "知识库检索工具集：发现空间、浏览知识库、搜索文档内容"

    def get_tools(self) -> list[dict[str, Any]]:
        """返回知识库检索工具集定义：空间发现、KB 浏览、文档检索、文档列表。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_spaces",
                    "description": (
                        "List all knowledge spaces the user can access. "
                        "Returns space ID, name, and description. "
                        "If the session has a knowledge scope configured, only in-scope spaces are listed. "
                        "Call this first when you need to discover what knowledge resources are available."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_knowledge_bases",
                    "description": (
                        "List all knowledge bases under a specific space. "
                        "Returns KB ID, name, and description. "
                        "Use after list_spaces to find relevant knowledge bases for the user's query."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "space_id": {
                                "type": "integer",
                                "description": "Knowledge space ID (from list_spaces)",
                            },
                        },
                        "required": ["space_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_all_knowledge_bases",
                    "description": (
                        "List ALL knowledge bases across ALL spaces in one call. "
                        "If the session has a knowledge scope configured, only in-scope KBs are listed. "
                        "Use this when you're unsure which space contains the relevant KB, "
                        "or when you want a quick overview without browsing spaces first."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "knowledge_search",
                    "description": (
                        "Search document content within a knowledge space. "
                        "Returns the most relevant text chunks with scores.\n\n"
                        "USAGE:\n"
                        "- Always provide space_id and query\n"
                        "- Provide kb_id for precise results within a specific knowledge base\n"
                        "- Omit kb_id to search across all KBs in the space (top 3 KBs)\n"
                        "- Default search_mode 'content_hybrid' (vector + BM25) works well for most cases\n"
                        "- Try different keywords if initial results aren't relevant\n\n"
                        "TIP: Use kb_id when you know which KB is relevant. "
                        "Without kb_id, results may be diluted across unrelated KBs."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "space_id": {
                                "type": "integer",
                                "description": "Knowledge space ID",
                            },
                            "query": {
                                "type": "string",
                                "description": "Search query text",
                            },
                            "kb_id": {
                                "type": "integer",
                                "description": "Knowledge base ID (optional, narrows search to a specific KB)",
                            },
                            "top_k": {
                                "type": "integer",
                                "description": "Number of results to return (default 5)",
                                "default": 5,
                            },
                            "search_mode": {
                                "type": "string",
                                "description": "Search mode: content_vector (semantic), content_bm25 (keyword), content_hybrid (both, recommended)",
                                "default": SearchMode.CONTENT_HYBRID.value,
                            },
                        },
                        "required": ["space_id", "query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "document_list",
                    "description": (
                        "List documents in a knowledge base. "
                        "Returns document ID, filename, status, and chunk count. "
                        "Useful to understand what content is available before searching."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "space_id": {
                                "type": "integer",
                                "description": "Knowledge space ID",
                            },
                            "kb_id": {
                                "type": "integer",
                                "description": "Knowledge base ID",
                            },
                            "page": {
                                "type": "integer",
                                "description": "Page number (default 1)",
                                "default": 1,
                            },
                            "page_size": {
                                "type": "integer",
                                "description": "Results per page (default 20)",
                                "default": 20,
                            },
                        },
                        "required": ["space_id", "kb_id"],
                    },
                },
            },
        ]

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """校验 context 中的检索端口后按工具名分发执行；端口未配置返回错误 JSON。

        Args:
            tool_name: 工具名：空间发现 / KB 浏览（单个与跨空间）/ 检索 / 文档列表五者之一。
            arguments: 工具参数（space_id/kb_id/query 等，逐工具不同）。
            context: 执行上下文：knowledge_search_port 与 user_id。

        Returns:
            JSON 文本：命中为结果集，无权限或异常为 {error}；未知工具为纯文本提示。
        """
        port = context.get("knowledge_search_port")
        if port is None:
            return json.dumps(
                {"error": "知识库检索端口未配置，无法执行知识库搜索"},
                ensure_ascii=False,
            )

        dispatch = {
            "list_spaces": lambda: self._list_spaces(port, context),
            "list_knowledge_bases": lambda: self._list_knowledge_bases(port, arguments, context),
            "list_all_knowledge_bases": lambda: self._list_all_knowledge_bases(port, context),
            "knowledge_search": lambda: self._search(port, arguments, context),
            "document_list": lambda: self._list_documents(port, arguments, context),
        }
        handler = dispatch.get(tool_name)
        if handler:
            return await handler()
        return f"未知工具：{tool_name}"

    # ==================== 空间与知识库发现 ====================

    @staticmethod
    def _session_bindings(context: dict[str, Any]) -> tuple[list[int] | None, list[int] | None]:
        """解析会话知识绑定，返回 (bound_space_ids, bound_kb_ids)；无绑定 both None。

        knowledge_pipeline 配置仅在主对话场景注入（chat_service）；task 子 agent 等
        场景无此键，视为不限定。
        """
        bindings = (context.get("knowledge_pipeline") or {}).get("knowledge_bindings") or {}
        return bindings.get("space_ids"), bindings.get("kb_ids")

    @staticmethod
    def _out_of_scope_error(bound_space_ids: list[int]) -> str:
        """越权拒绝响应（与检索端同文案，模型侧错误口径一致）。"""
        return json.dumps(
            {"error": f"当前会话知识范围限定为空间 {bound_space_ids}，不在范围内的空间不可访问"},
            ensure_ascii=False,
        )

    async def _list_spaces(self, port, context: dict[str, Any]) -> str:
        """列出用户可访问的知识空间；会话绑定 space_ids 时只返回绑定内空间。"""
        try:
            user_id = context["user_id"]
            spaces = await port.list_spaces(user_id)
            bound_space_ids, _ = self._session_bindings(context)
            if bound_space_ids:
                spaces = [s for s in spaces if s.id in bound_space_ids]

            result = [
                {"id": s.id, "name": s.name, "description": s.description}
                for s in spaces
            ]
            return json.dumps(
                {"total": len(result), "spaces": result},
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            logger.error("获取空间列表失败", error=str(e))
            return json.dumps({"error": f"获取空间列表失败：{str(e)}"}, ensure_ascii=False)

    async def _list_knowledge_bases(
        self, port, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """列出指定空间下的知识库；会话绑定时越权拒绝，绑定 kb_ids 则过滤。"""
        try:
            user_id = context["user_id"]
            space_id = args["space_id"]
            bound_space_ids, bound_kb_ids = self._session_bindings(context)

            # 会话限定 space 集合：越权空间直接拒绝（与检索端口径一致）
            if bound_space_ids and space_id not in bound_space_ids:
                return self._out_of_scope_error(bound_space_ids)

            # 校验空间访问权限（与旧路径一致，先校验后列）
            if not await port.can_access_space(space_id, user_id):
                return json.dumps(
                    {"error": f"无权访问空间 {space_id}，请确认空间ID是否正确或您是否有权限"},
                    ensure_ascii=False,
                )

            kbs = await port.list_knowledge_bases(space_id, user_id)
            if bound_kb_ids:
                kbs = [kb for kb in kbs if kb.id in bound_kb_ids]
            result = [
                {
                    "id": kb.id,
                    "name": kb.name,
                    "description": kb.description,
                    "space_id": kb.space_id,
                }
                for kb in kbs
            ]
            return json.dumps(
                {"space_id": space_id, "total": len(result), "knowledge_bases": result},
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            logger.error("获取知识库列表失败", error=str(e))
            return json.dumps({"error": f"获取知识库列表失败：{str(e)}"}, ensure_ascii=False)

    async def _list_all_knowledge_bases(self, port, context: dict[str, Any]) -> str:
        """跨空间列出用户所有可访问的知识库；会话绑定时只返回范围内 KB。"""
        try:
            user_id = context["user_id"]
            kbs = await port.list_all_knowledge_bases(user_id)
            bound_space_ids, bound_kb_ids = self._session_bindings(context)
            if bound_space_ids:
                kbs = [kb for kb in kbs if kb.space_id in bound_space_ids]
            if bound_kb_ids:
                kbs = [kb for kb in kbs if kb.id in bound_kb_ids]

            result = [
                {
                    "id": kb.id,
                    "name": kb.name,
                    "description": kb.description,
                    "space_id": kb.space_id,
                    "space_name": kb.space_name,
                }
                for kb in kbs
            ]
            return json.dumps(
                {"total": len(result), "knowledge_bases": result},
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            logger.error("获取全部知识库失败", error=str(e))
            return json.dumps({"error": f"获取全部知识库失败：{str(e)}"}, ensure_ascii=False)

    # ==================== 搜索与文档列表 ====================

    async def _search(self, port, args: dict[str, Any], context: dict[str, Any]) -> str:
        """检索用户可见知识库，返回格式化的命中列表 JSON。

        context 带 knowledge_pipeline 配置（会话级知识绑定 + 会话模型，主对话场景由
        chat_service 注入）时走质量管线（改写→检索→grade→阈值→insufficient_evidence
        拒答声明）；无配置走裸检索（task 子 agent 等场景，行为不变）。
        """
        try:
            user_id: int = context["user_id"]

            space_id = args["space_id"]
            query = args["query"]
            kb_id = args.get("kb_id")
            top_k = args.get("top_k", 5)
            search_mode = args.get("search_mode", SearchMode.CONTENT_HYBRID.value)

            pipeline_cfg = context.get("knowledge_pipeline")
            if pipeline_cfg:
                return await self._pipeline_search(port, args, pipeline_cfg, context)

            items = await port.search(
                space_id=space_id,
                user_id=user_id,
                query=query,
                top_k=top_k,
                search_mode=search_mode,
                kb_id=kb_id,
            )

            if not items:
                return json.dumps(
                    {"message": "未找到相关结果", "query": query},
                    ensure_ascii=False,
                )

            formatted = []
            for item in items:
                row = {
                    "content": item.content[:500],
                    "score": round(item.score, 4),
                    "document_id": item.document_id,
                    "chunk_id": item.chunk_id,
                }
                if item.file_info:
                    row["filename"] = item.file_info.get("filename", "")
                formatted.append(row)

            return json.dumps(
                {"query": query, "total": len(formatted), "results": formatted},
                ensure_ascii=False,
                indent=2,
            )

        except Exception as e:
            logger.error("知识库搜索失败", error=str(e))
            return json.dumps({"error": f"搜索失败：{str(e)}"}, ensure_ascii=False)

    async def _pipeline_search(
        self, port, args: dict[str, Any], cfg: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """走质量管线的检索：注入会话绑定范围约束，结果附检索质量元数据。

        范围约束优先级（没选不兜底）：会话绑定 kb_ids 显式给定时忽略工具入参 kb_id
        （会话约束是用户声明，工具入参越权扩域）；仅 space_ids 时取交集。
        """
        user_id: int = context["user_id"]
        space_id = args["space_id"]
        query = args["query"]
        top_k = args.get("top_k", 5)
        search_mode = args.get("search_mode", SearchMode.CONTENT_HYBRID.value)

        bindings = cfg.get("knowledge_bindings") or {}
        bound_space_ids = bindings.get("space_ids")
        bound_kb_ids = bindings.get("kb_ids")

        # 会话限定了 space 集合：请求空间必须在集合内（越权拒绝而非静默放行）
        if bound_space_ids and space_id not in bound_space_ids:
            return json.dumps(
                {
                    "error": (
                        f"当前会话知识范围限定为空间 {bound_space_ids}，"
                        f"空间 {space_id} 不在范围内"
                    )
                },
                ensure_ascii=False,
            )

        kb_ids: list[int] | None = bound_kb_ids or ([args["kb_id"]] if args.get("kb_id") else None)

        result = await port.pipeline_search(
            space_id=space_id,
            user_id=user_id,
            query=query,
            llm_client=cfg.get("llm_client"),
            conversation_history=cfg.get("conversation_history"),
            rewrite_strategy=cfg.get("rewrite_strategy", "completion"),
            grade_retry_enabled=bool(cfg.get("grade_retry_enabled", False)),
            grade_passing_score=int(cfg.get("grade_passing_score", 5)),
            score_threshold=cfg.get("score_threshold", 0.3),
            top_k=top_k,
            search_mode=search_mode,
            kb_ids=kb_ids,
        )

        items = result["items"]
        payload: dict[str, Any] = {
            "query": query,
            "total": len(items),
            "insufficient_evidence": result["insufficient_evidence"],
        }
        if result["rewritten_query"] != query:
            payload["rewritten_query"] = result["rewritten_query"]
        if result["rewrite_degraded"]:
            payload["rewrite_degraded"] = True
        if result["grade_traces"]:
            payload["grade_traces"] = result["grade_traces"]

        if not items:
            payload["message"] = (
                "检索结果经质量过滤后为空（证据不足）"
                if result["insufficient_evidence"]
                else "未找到相关结果"
            )
            return json.dumps(payload, ensure_ascii=False, indent=2)

        payload["results"] = [
            {
                "content": item.content[:500],
                "score": round(item.score, 4),
                "document_id": item.document_id,
                "chunk_id": item.chunk_id,
                **(
                    {"filename": item.file_info.get("filename", "")}
                    if item.file_info else {}
                ),
            }
            for item in items
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def _list_documents(
        self, port, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """列出文档；会话绑定时越权空间/知识库拒绝，绑定 kb_ids 时限定单库。"""
        try:
            user_id = context["user_id"]
            space_id = args["space_id"]
            kb_id = args["kb_id"]
            page = args.get("page", 1)
            page_size = args.get("page_size", 20)
            bound_space_ids, bound_kb_ids = self._session_bindings(context)

            if bound_space_ids and space_id not in bound_space_ids:
                return self._out_of_scope_error(bound_space_ids)
            if bound_kb_ids and kb_id not in bound_kb_ids:
                return json.dumps(
                    {
                        "error": (
                            f"当前会话知识范围限定为知识库 {bound_kb_ids}，"
                            f"知识库 {kb_id} 不在范围内"
                        )
                    },
                    ensure_ascii=False,
                )

            # 校验空间访问权限（与旧路径一致，先校验后列）
            if not await port.can_access_space(space_id, user_id):
                return json.dumps(
                    {"error": f"无权访问空间 {space_id}，请确认空间ID是否正确或您是否有权限"},
                    ensure_ascii=False,
                )

            result = await port.list_documents(
                space_id=space_id,
                kb_id=kb_id,
                user_id=user_id,
                page=page,
                page_size=page_size,
            )

            docs = [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "status": d.status,
                    "chunk_count": d.chunk_count,
                }
                for d in result.documents
            ]
            return json.dumps(
                {"kb_id": kb_id, "total": result.total, "documents": docs},
                ensure_ascii=False,
                indent=2,
            )

        except Exception as e:
            logger.error("文档列表获取失败", error=str(e))
            return json.dumps({"error": f"获取文档列表失败：{str(e)}"}, ensure_ascii=False)

    def get_system_prompt_fragment(self) -> str:
        """返回知识库检索的使用指导片段（先发现后检索、按需换词换库）。"""
        return (
            "## Knowledge Search\n"
            "When the user's question relates to their stored documents:\n"
            "1. Discover: use list_spaces or list_all_knowledge_bases to find available resources\n"
            "2. Select: identify the most relevant knowledge base for the query\n"
            "3. Search: use knowledge_search with a clear, specific query\n"
            "4. If results are poor, try different keywords or search a different KB\n\n"
            "Guidelines:\n"
            "- Matching the right KB to the query matters more than search_mode tuning\n"
            "- Do NOT call these tools unless the question actually relates to stored documents\n"
            "- If search returns no results, try rephrasing the query before concluding the info is absent"
        )