"""
KnowledgeSearchPort 宿主适配器，包装 knowledge_space repository 与 SearchService。

权限校验、跨库合并等业务逻辑在此实现。
"""
from typing import Any, Dict, List, Optional

from novamind.engines.agent.ports import (
    DocumentInfo,
    DocumentListResult,
    KbInfo,
    KnowledgeSearchItem,
    KnowledgeSearchPort,
    SpaceInfo,
)


class HostKnowledgeSearchPort:
    """KnowledgeSearchPort 宿主实现。"""

    def __init__(
        self,
        db: Any,
        model_config_service: Any,
        es_client: Optional[Any] = None,
    ):
        self._db = db
        self._mcs = model_config_service
        self._es_client = es_client

    # ==================== 内部装配 ====================

    async def _get_es_client(self) -> Any:
        if self._es_client is None:
            from novamind.shared.storage.client_factory import get_elasticsearch_client

            self._es_client = await get_elasticsearch_client()
        return self._es_client

    async def _build_search_service(self) -> Any:
        from novamind.features.knowledge_space.services.search_service import (
            SearchService,
        )

        es_client = await self._get_es_client()
        return SearchService(self._db, es_client, self._mcs)

    # ==================== 权限校验 ====================

    async def can_access_space(self, space_id: int, user_id: int) -> bool:
        """对齐旧 _check_space_access。"""
        from novamind.features.knowledge_space.repository.space_repository import (
            SpaceRepository,
        )
        from novamind.features.knowledge_space.repository.member_repository import (
            MemberRepository,
        )
        from novamind.features.knowledge_space.models.knowledge_space import (
            SpaceStatus,
            SpaceVisibility,
        )
        from novamind.features.user.models.user import User

        space_repo = SpaceRepository(self._db)
        member_repo = MemberRepository(self._db)

        space = await space_repo.get_by_id(space_id)
        if not space:
            return False
        if space.is_deleted() or space.status != SpaceStatus.ACTIVE:
            return False

        user = await self._db.get(User, user_id)
        if user and user.is_admin:
            return True

        if await member_repo.is_member(space_id, user_id):
            return True

        if space.visibility == SpaceVisibility.PUBLIC:
            return True
        return False

    # ==================== 空间与知识库发现 ====================

    async def list_spaces(self, user_id: int) -> List[SpaceInfo]:
        from novamind.features.knowledge_space.repository.space_repository import (
            SpaceRepository,
        )

        repo = SpaceRepository(self._db)
        spaces = await repo.get_user_spaces(user_id)
        return [
            SpaceInfo(
                id=space.id,
                name=space.name,
                description=space.get_description() or "",
            )
            for space in spaces
        ]

    async def list_knowledge_bases(
        self, space_id: int, user_id: int
    ) -> List[KbInfo]:
        from novamind.features.knowledge_space.repository.knowledge_base_repository import (
            KnowledgeBaseRepository,
            KnowledgeBaseStatus,
        )

        repo = KnowledgeBaseRepository(self._db)
        kbs = await repo.get_by_space(space_id, status=KnowledgeBaseStatus.ACTIVE)
        return [
            KbInfo(
                id=kb.id,
                name=kb.name,
                space_id=kb.space_id,
                description=kb.get_description() or "",
            )
            for kb in kbs
        ]

    async def list_all_knowledge_bases(self, user_id: int) -> List[KbInfo]:
        from novamind.features.knowledge_space.repository.space_repository import (
            SpaceRepository,
        )
        from novamind.features.knowledge_space.repository.knowledge_base_repository import (
            KnowledgeBaseRepository,
            KnowledgeBaseStatus,
        )

        space_repo = SpaceRepository(self._db)
        kb_repo = KnowledgeBaseRepository(self._db)

        spaces = await space_repo.get_user_spaces(user_id)
        result: List[KbInfo] = []
        for space in spaces:
            kbs = await kb_repo.get_by_space(space.id, status=KnowledgeBaseStatus.ACTIVE)
            for kb in kbs:
                result.append(
                    KbInfo(
                        id=kb.id,
                        name=kb.name,
                        space_id=kb.space_id,
                        description=kb.get_description() or "",
                        space_name=space.name,
                    )
                )
        return result

    # ==================== 搜索与文档列表 ====================

    async def search(
        self,
        space_id: int,
        user_id: int,
        query: str,
        top_k: int = 5,
        search_mode: str = "content_hybrid",
        kb_id: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> List[KnowledgeSearchItem]:
        from novamind.features.knowledge_space.schemas.search_schema import (
            SearchRequest,
        )
        from novamind.features.knowledge_space.repository.knowledge_base_repository import (
            KnowledgeBaseRepository,
        )

        search_request = SearchRequest(
            query=query,
            search_mode=search_mode,
            top_k=top_k,
            score_threshold=score_threshold if score_threshold is not None else 0.0,
        )
        search_service = await self._build_search_service()

        if kb_id:
            result = await search_service.search(
                space_id=space_id,
                kb_id=kb_id,
                user_id=user_id,
                request=search_request,
            )
            raw_results: List[Dict[str, Any]] = result.get("results", [])
        else:
            kb_repo = KnowledgeBaseRepository(self._db)
            kbs = await kb_repo.get_by_space(space_id)
            if not kbs:
                return []

            all_results: List[Dict[str, Any]] = []
            for kb in kbs[:3]:
                try:
                    r = await search_service.search(
                        space_id=space_id,
                        kb_id=kb.id,
                        user_id=user_id,
                        request=search_request,
                    )
                    all_results.extend(r.get("results", []))
                except Exception:
                    continue
            all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            raw_results = all_results[:top_k]

        items: List[KnowledgeSearchItem] = []
        for r in raw_results:
            items.append(
                KnowledgeSearchItem(
                    content=r.get("content", ""),
                    score=r.get("score", 0),
                    document_id=r.get("document_id"),
                    chunk_id=r.get("chunk_id"),
                    file_info=r.get("file_info"),
                )
            )
        return items

    async def list_documents(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> DocumentListResult:
        from novamind.features.knowledge_space.repository.document_repository import (
            DocumentRepository,
        )

        doc_repo = DocumentRepository(self._db)
        skip = (page - 1) * page_size
        documents = await doc_repo.get_by_kb(kb_id=kb_id, skip=skip, limit=page_size)
        total = await doc_repo.count_by_kb(kb_id=kb_id)

        docs = [
            DocumentInfo(
                id=doc.id,
                filename=doc.filename,
            )
            for doc in documents
        ]
        return DocumentListResult(total=total, documents=docs)


def as_knowledge_search_port(
    db: Any, model_config_service: Any, es_client: Optional[Any] = None
) -> KnowledgeSearchPort:
    """构造 KnowledgeSearchPort 实例（供装配点注入 context）。"""
    return HostKnowledgeSearchPort(db, model_config_service, es_client)  # type: ignore[return-value]