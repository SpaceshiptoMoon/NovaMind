"""
内置工具：知识库搜索

提供知识空间发现、知识库浏览、文档检索的完整工具链。
工具使用流程：空间(list_spaces) → 知识库(list_knowledge_bases) → 搜索(knowledge_search)

端口化：宿主在装配时注入 KnowledgeSearchPort 到 context，工具经端口调用
知识空间/用户 feature 能力，不再直接 import features.knowledge_space/features.user。
"""
import json
from typing import Any, Dict, List

from novamind.engines.agent.tool.base import BaseTool
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

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_spaces",
                    "description": (
                        "List all knowledge spaces the user can access. "
                        "Returns space ID, name, and description. "
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
                                "default": "content_hybrid",
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
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
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

    async def _list_spaces(self, port, context: Dict[str, Any]) -> str:
        """列出用户可访问的知识空间"""
        try:
            user_id = context["user_id"]
            spaces = await port.list_spaces(user_id)

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
        self, port, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """列出指定空间下的知识库"""
        try:
            user_id = context["user_id"]
            space_id = args["space_id"]

            # 校验空间访问权限（与旧路径一致，先校验后列）
            if not await port.can_access_space(space_id, user_id):
                return json.dumps(
                    {"error": f"无权访问空间 {space_id}，请确认空间ID是否正确或您是否有权限"},
                    ensure_ascii=False,
                )

            kbs = await port.list_knowledge_bases(space_id, user_id)
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

    async def _list_all_knowledge_bases(self, port, context: Dict[str, Any]) -> str:
        """跨空间列出用户所有可访问的知识库"""
        try:
            user_id = context["user_id"]
            kbs = await port.list_all_knowledge_bases(user_id)

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

    async def _search(self, port, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        """执行知识库搜索"""
        try:
            user_id: int = context["user_id"]

            space_id = args["space_id"]
            query = args["query"]
            kb_id = args.get("kb_id")
            top_k = args.get("top_k", 5)
            search_mode = args.get("search_mode", "content_hybrid")

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

    async def _list_documents(
        self, port, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """列出文档"""
        try:
            user_id = context["user_id"]
            space_id = args["space_id"]
            kb_id = args["kb_id"]
            page = args.get("page", 1)
            page_size = args.get("page_size", 20)

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