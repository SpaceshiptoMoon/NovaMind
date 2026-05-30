"""
内置工具：知识库搜索

提供知识空间发现、知识库浏览、文档检索的完整工具链。
工具使用流程：空间(list_spaces) → 知识库(list_knowledge_bases) → 搜索(knowledge_search)
"""
import json
from typing import Any, Dict, List

from src.features.agent.core.tool.base import BaseTool
from src.shared.prompts import PromptManager, PromptTemplate
from src.core.middleware.structured_logging import get_logger

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
        dispatch = {
            "list_spaces": lambda: self._list_spaces(context),
            "list_knowledge_bases": lambda: self._list_knowledge_bases(arguments, context),
            "list_all_knowledge_bases": lambda: self._list_all_knowledge_bases(context),
            "knowledge_search": lambda: self._search(arguments, context),
            "document_list": lambda: self._list_documents(arguments, context),
        }
        handler = dispatch.get(tool_name)
        if handler:
            return await handler()
        return f"未知工具：{tool_name}"

    # ==================== 权限校验 ====================

    async def _check_space_access(
        self, db, space_id: int, user_id: int
    ) -> bool:
        """
        校验用户是否有权访问指定空间。

        规则与 validate_space_access 一致：
        - 空间必须存在且状态为 ACTIVE
        - 系统管理员拥有所有空间的访问权限
        - 用户是空间成员（ACTIVE 状态）则允许
        - 非成员但空间为 PUBLIC 则允许
        - 其余情况拒绝访问

        Args:
            db: 数据库会话
            space_id: 空间 ID
            user_id: 用户 ID

        Returns:
            True 表示有权限，False 表示无权限
        """
        from src.features.knowledge_space.repository.space_repository import SpaceRepository
        from src.features.knowledge_space.repository.member_repository import MemberRepository
        from src.features.knowledge_space.models.knowledge_space import SpaceStatus, SpaceVisibility
        from src.features.user.models.user import User

        space_repo = SpaceRepository(db)
        member_repo = MemberRepository(db)

        # 获取空间
        space = await space_repo.get_by_id(space_id)
        if not space:
            return False

        # 检查空间状态
        if space.is_deleted() or space.status != SpaceStatus.ACTIVE:
            return False

        # 系统管理员直接放行
        user = await db.get(User, user_id)
        if user and user.is_admin:
            return True

        # 检查是否是空间成员
        is_member = await member_repo.is_member(space_id, user_id)
        if is_member:
            return True

        # 非成员：仅公开空间允许访问
        if space.visibility == SpaceVisibility.PUBLIC:
            return True

        return False

    # ==================== 空间与知识库发现 ====================

    async def _list_spaces(self, context: Dict[str, Any]) -> str:
        """列出用户可访问的知识空间"""
        try:
            from src.features.knowledge_space.repository.space_repository import SpaceRepository

            db = context["db_session"]
            user_id = context["user_id"]

            repo = SpaceRepository(db)
            spaces = await repo.get_user_spaces(user_id)

            result = []
            for space in spaces:
                result.append({
                    "id": space.id,
                    "name": space.name,
                    "description": space.get_description() or "",
                })

            return json.dumps(
                {"total": len(result), "spaces": result},
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            logger.error("获取空间列表失败", error=str(e))
            return json.dumps({"error": f"获取空间列表失败：{str(e)}"}, ensure_ascii=False)

    async def _list_knowledge_bases(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        """列出指定空间下的知识库"""
        try:
            from src.features.knowledge_space.repository.knowledge_base_repository import (
                KnowledgeBaseRepository,
                KnowledgeBaseStatus,
            )

            db = context["db_session"]
            user_id = context["user_id"]
            space_id = args["space_id"]

            # 校验空间访问权限
            if not await self._check_space_access(db, space_id, user_id):
                return json.dumps(
                    {"error": f"无权访问空间 {space_id}，请确认空间ID是否正确或您是否有权限"},
                    ensure_ascii=False,
                )

            repo = KnowledgeBaseRepository(db)
            kbs = await repo.get_by_space(space_id, status=KnowledgeBaseStatus.ACTIVE)

            result = []
            for kb in kbs:
                result.append({
                    "id": kb.id,
                    "name": kb.name,
                    "description": kb.get_description() or "",
                    "space_id": kb.space_id,
                })

            return json.dumps(
                {"space_id": space_id, "total": len(result), "knowledge_bases": result},
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            logger.error("获取知识库列表失败", error=str(e))
            return json.dumps({"error": f"获取知识库列表失败：{str(e)}"}, ensure_ascii=False)

    async def _list_all_knowledge_bases(self, context: Dict[str, Any]) -> str:
        """跨空间列出用户所有可访问的知识库"""
        try:
            from src.features.knowledge_space.repository.space_repository import SpaceRepository
            from src.features.knowledge_space.repository.knowledge_base_repository import (
                KnowledgeBaseRepository,
                KnowledgeBaseStatus,
            )

            db = context["db_session"]
            user_id = context["user_id"]

            space_repo = SpaceRepository(db)
            kb_repo = KnowledgeBaseRepository(db)

            spaces = await space_repo.get_user_spaces(user_id)

            result = []
            space_map = {}
            for space in spaces:
                space_map[space.id] = space.name
                kbs = await kb_repo.get_by_space(space.id, status=KnowledgeBaseStatus.ACTIVE)
                for kb in kbs:
                    result.append({
                        "id": kb.id,
                        "name": kb.name,
                        "description": kb.get_description() or "",
                        "space_id": kb.space_id,
                        "space_name": space.name,
                    })

            return json.dumps(
                {"total": len(result), "knowledge_bases": result},
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            logger.error("获取全部知识库失败", error=str(e))
            return json.dumps({"error": f"获取全部知识库失败：{str(e)}"}, ensure_ascii=False)

    # ==================== 搜索与文档列表 ====================

    async def _search(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        """执行知识库搜索"""
        try:
            from src.features.knowledge_space.services.search_service import SearchService
            from src.features.knowledge_space.schemas.search_schema import SearchRequest
            from src.shared.clients import get_elasticsearch_client
            from src.features.user.services.model_config_service import ModelConfigService

            db = context["db_session"]
            user_id: int = context["user_id"]

            space_id = args["space_id"]
            query = args["query"]
            kb_id = args.get("kb_id")
            top_k = args.get("top_k", 5)
            search_mode = args.get("search_mode", "content_hybrid")

            search_request = SearchRequest(
                query=query,
                search_mode=search_mode,
                top_k=top_k,
            )

            es_client = await get_elasticsearch_client()
            model_config_service = ModelConfigService(db)
            search_service = SearchService(db, es_client, model_config_service)

            if kb_id:
                result = await search_service.search(
                    space_id=space_id,
                    kb_id=kb_id,
                    user_id=user_id,
                    request=search_request,
                )
            else:
                from src.features.knowledge_space.repository.knowledge_base_repository import (
                    KnowledgeBaseRepository,
                )

                kb_repo = KnowledgeBaseRepository(db)
                kbs = await kb_repo.get_by_space(space_id)
                if not kbs:
                    return json.dumps(
                        {"error": "该空间下没有知识库", "space_id": space_id},
                        ensure_ascii=False,
                    )

                all_results = []
                for kb in kbs[:3]:
                    try:
                        r = await search_service.search(
                            space_id=space_id,
                            kb_id=kb.id,
                            user_id=user_id,
                            request=search_request,
                        )
                        all_results.extend(r.get("results", []))
                    except Exception as e:
                        logger.warning("知识库检索失败，跳过", kb_id=kb.id, error=str(e))
                        continue

                all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
                result = {"results": all_results[:top_k], "query": query}

            results = result.get("results", [])
            if not results:
                return json.dumps(
                    {"message": "未找到相关结果", "query": query},
                    ensure_ascii=False,
                )

            formatted = []
            for r in results:
                item = {
                    "content": r.get("content", "")[:500],
                    "score": round(r.get("score", 0), 4),
                    "document_id": r.get("document_id"),
                    "chunk_id": r.get("chunk_id"),
                }
                if r.get("file_info"):
                    item["filename"] = r["file_info"].get("filename", "")
                formatted.append(item)

            return json.dumps(
                {"query": query, "total": len(formatted), "results": formatted},
                ensure_ascii=False,
                indent=2,
            )

        except Exception as e:
            logger.error("知识库搜索失败", error=str(e))
            return json.dumps({"error": f"搜索失败：{str(e)}"}, ensure_ascii=False)

    async def _list_documents(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        """列出文档"""
        try:
            from src.features.knowledge_space.repository.document_repository import (
                DocumentRepository,
            )

            db = context["db_session"]
            user_id = context["user_id"]
            space_id = args["space_id"]
            kb_id = args["kb_id"]
            page = args.get("page", 1)
            page_size = args.get("page_size", 20)

            # 校验空间访问权限
            if not await self._check_space_access(db, space_id, user_id):
                return json.dumps(
                    {"error": f"无权访问空间 {space_id}，请确认空间ID是否正确或您是否有权限"},
                    ensure_ascii=False,
                )

            doc_repo = DocumentRepository(db)
            skip = (page - 1) * page_size
            documents = await doc_repo.get_by_kb(
                kb_id=kb_id, skip=skip, limit=page_size
            )
            total = await doc_repo.count_by_kb(kb_id=kb_id)

            docs = []
            for doc in documents:
                docs.append(
                    {
                        "id": doc.id,
                        "filename": doc.filename,
                        "status": doc.status.value if hasattr(doc.status, "value") else str(doc.status),
                        "chunk_count": doc.doc_metadata.get("chunk_count", 0) if doc.doc_metadata else 0,
                    }
                )

            return json.dumps(
                {
                    "kb_id": kb_id,
                    "total": total,
                    "documents": docs,
                },
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