"""
HostKnowledgeSearchPort 宿主适配器：为 agent 引擎提供空间/知识库发现与检索。

跨 feature 消费走 knowledge_space 公共面（R2）：权限判定走
``services/access_service.check_space_access``，空间/KB/文档发现走
SpaceService/KnowledgeBaseService/DocumentQueryService 公共方法，
检索委托 SearchService——不直接触碰对方 repository。
"""
from typing import Any

from novamind.engines.agent.context_types import (
    DocumentInfo,
    DocumentListResult,
    KbInfo,
    KnowledgeSearchItem,
    SpaceInfo,
)
from novamind.features.knowledge_space.schemas.search_schema import SearchMode


class HostKnowledgeSearchPort:
    """HostKnowledgeSearchPort 宿主实现。"""

    def __init__(
        self,
        db: Any,
        model_config_service: Any,
        es_client: Any | None = None,
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

    def _space_service(self) -> Any:
        from novamind.features.knowledge_space.services.space_service import (
            SpaceService,
        )

        return SpaceService(self._db)

    def _kb_service(self) -> Any:
        from novamind.features.knowledge_space.services.knowledge_base_service import (
            KnowledgeBaseService,
        )

        return KnowledgeBaseService(self._db, es_client=None, minio_client=None)

    def _doc_query_service(self) -> Any:
        from novamind.features.knowledge_space.services.document_query_service import (
            DocumentQueryService,
        )

        # list_documents 只走 KB 文档查询面（doc repo），minio/es 未用到，传 None
        return DocumentQueryService(self._db, minio_client=None, es_client=None)

    # ==================== 权限校验 ====================

    async def can_access_space(self, space_id: int, user_id: int) -> bool:
        """空间级访问判定，委托 knowledge_space 权限中心。"""
        from novamind.features.knowledge_space.services.access_service import (
            check_space_access,
        )

        return await check_space_access(self._db, space_id, user_id)

    # ==================== 空间与知识库发现 ====================

    async def list_spaces(self, user_id: int) -> list[SpaceInfo]:
        spaces = await self._space_service().get_user_spaces(user_id)
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
    ) -> list[KbInfo]:
        from novamind.features.knowledge_space.models.knowledge_base import (
            KnowledgeBaseStatus,
        )

        kbs = await self._kb_service().get_space_knowledge_bases(
            space_id, status=KnowledgeBaseStatus.ACTIVE
        )
        return [
            KbInfo(
                id=kb.id,
                name=kb.name,
                space_id=kb.space_id,
                description=kb.get_description() or "",
            )
            for kb in kbs
        ]

    async def list_all_knowledge_bases(self, user_id: int) -> list[KbInfo]:
        from novamind.features.knowledge_space.models.knowledge_base import (
            KnowledgeBaseStatus,
        )

        space_service = self._space_service()
        kb_service = self._kb_service()

        spaces = await space_service.get_user_spaces(user_id)
        result: list[KbInfo] = []
        for space in spaces:
            kbs = await kb_service.get_space_knowledge_bases(
                space.id, status=KnowledgeBaseStatus.ACTIVE
            )
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
        search_mode: str = SearchMode.CONTENT_HYBRID.value,
        kb_id: int | None = None,
        score_threshold: float | None = None,
    ) -> list[KnowledgeSearchItem]:
        from novamind.features.knowledge_space.schemas.search_schema import (
            SearchRequest,
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
            raw_results: list[dict[str, Any]] = result.get("results", [])
        else:
            # kb_id 缺省：空间下全部 KB，跨库检索取前 3 个合并
            kbs = await self._kb_service().get_space_knowledge_bases(space_id)
            if not kbs:
                return []

            all_results: list[dict[str, Any]] = []
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

        items: list[KnowledgeSearchItem] = []
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
        doc_service = self._doc_query_service()
        skip = (page - 1) * page_size
        documents = await doc_service.get_kb_documents(kb_id=kb_id, skip=skip, limit=page_size)
        total = await doc_service.count_kb_documents(kb_id=kb_id)

        docs = [
            DocumentInfo(
                id=doc.id,
                filename=doc.filename,
            )
            for doc in documents
        ]
        return DocumentListResult(total=total, documents=docs)
