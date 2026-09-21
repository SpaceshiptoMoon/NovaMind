"""InternalSearchPort 宿主适配器。

引擎 ``DeepResearchEngine.search`` 经本宿主类调多租户 KB 检索（批次 3.4 去 Protocol，直收 SearchService），
切断引擎对 ORM/setting/knowledge_space 的依赖。本适配器下沉所有跨 feature / ORM import
（``knowledge_space`` models/schemas/repository、``KnowledgeBaseStatus``、
``SearchRequest``/``WeightConfig``/``RerankConfig``/``SearchMode``），引擎层零宿主依赖。

每请求构造（绑定 ``space_id``/``user_id``/``internal_config``），不跨请求复用。
"""
from typing import Any

from novamind.engines.deep_research.sources import (
    SearchSourceContext,
    SearchSourcePort,
)
from novamind.engines.deep_research.types import SourceType
from novamind.features.deep_research.exceptions import DeepResearchError
from novamind.features.deep_research.schemas.research_schema import InternalSearchConfig
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBaseStatus
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.schemas.search_schema import (
    RerankConfig,
    SearchMode,
    SearchRequest,
    WeightConfig,
)
from novamind.features.knowledge_space.services.search_service import SearchService


class HostInternalSearchPort:
    """``InternalSearchPort`` 宿主实现：委托 ``SearchService``（包 SearchService）做
    多租户 KB 检索，归一化结果为统一 dict 形状（与引擎纯函数及 feature 持久化一致）。

    体等价于原 ``DeepResearchService._execute_internal_search``：按 ``space_id`` 过滤
    活跃知识库 → 构 ``SearchRequest``/``WeightConfig``/``RerankConfig`` → 逐 KB 调
    ``search_port.search`` → merge/sort/top_k → 归一化 dict。
    """

    def __init__(
        self,
        search_port: "SearchService",
        kb_repo: KnowledgeBaseRepository,
        space_id: int,
        user_id: int,
        internal_config: InternalSearchConfig,
        logger: object | None = None,
    ):
        self._search_port = search_port
        self._kb_repo = kb_repo
        self._space_id = space_id
        self._user_id = user_id
        self._config = internal_config
        self._logger = logger

    async def search(self, query: str, *, top_k: int = 10) -> list[dict[str, Any]]:
        """执行内部 RAG 检索，返回归一化结果字典列表。"""
        config = self._config
        space_id = self._space_id
        user_id = self._user_id
        try:
            # 确定要搜索的知识库（仅搜索活跃状态的知识库）
            if config.kb_ids:
                kbs = []
                for kb_id in config.kb_ids:
                    kb = await self._kb_repo.get_by_id(kb_id)
                    if kb and kb.space_id == space_id and kb.status == KnowledgeBaseStatus.ACTIVE:
                        kbs.append(kb)
            else:
                all_kbs = await self._kb_repo.get_by_space(space_id)
                kbs = [kb for kb in all_kbs if kb.status == KnowledgeBaseStatus.ACTIVE]

            if not kbs:
                if self._logger is not None:
                    self._logger.warning("空间无可用知识库，跳过内部检索", space_id=space_id)
                return []

            # 构建检索请求
            weights = WeightConfig(
                vector_weight=config.vector_weight,
                bm25_weight=config.bm25_weight,
            )
            rerank_config = None
            if config.rerank_enabled:
                rerank_config = RerankConfig(
                    enabled=True,
                    top_k=config.rerank_top_k,
                    model=config.rerank_model,
                )

            search_req = SearchRequest(
                query=query,
                search_mode=SearchMode(config.search_mode),
                top_k=config.top_k,
                weights=weights,
                rerank=rerank_config,
                score_threshold=config.score_threshold,
            )

            # 顺序搜索所有知识库并合并结果（共享 session 不能并发）
            search_results = []
            for kb in kbs:
                try:
                    result = await self._search_port.search(
                        space_id=space_id,
                        kb_id=kb.id,
                        user_id=user_id,
                        request=search_req,
                    )
                    search_results.append(result)
                except Exception as e:
                    if self._logger is not None:
                        self._logger.warning("知识库搜索失败", kb_id=kb.id, error=str(e))
                    search_results.append({"results": []})

            all_results = []
            for kb, search_result in zip(kbs, search_results):
                for r in search_result.get("results", []):
                    all_results.append({
                        "source_type": SourceType.INTERNAL.value,
                        "content": r.get("content", ""),
                        "document_id": r.get("document_id"),
                        "chunk_id": r.get("chunk_id"),
                        "document_name": r.get("file_info", {}).get("filename") or r.get("document_name"),
                        "kb_id": kb.id,
                        "kb_name": kb.name,
                        "score": r.get("score", 0),
                    })

            # 按 score 排序并截取 top_k
            all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            return all_results[: config.top_k]
        except Exception as e:
            if self._logger is not None:
                self._logger.warning("内部检索失败", query=query, error=str(e))
            raise DeepResearchError("内部检索失败，请稍后重试")


def as_internal_search_port(
    search_port: SearchService,
    kb_repo: KnowledgeBaseRepository,
    space_id: int,
    user_id: int,
    internal_config: InternalSearchConfig,
    logger: object | None = None,
) -> HostInternalSearchPort:
    """构造内部检索宿主实例（供装配点注入引擎）。"""
    return HostInternalSearchPort(
        search_port=search_port,
        kb_repo=kb_repo,
        space_id=space_id,
        user_id=user_id,
        internal_config=internal_config,
        logger=logger,
    )


def build_internal_source(context: SearchSourceContext) -> SearchSourcePort:
    """内部知识库数据源注册表工厂：ctx → HostInternalSearchPort。

    - ``ctx.config``：InternalSearchConfig dump（kb_ids/search_mode/top_k/...）
    - ``ctx.deps``：宿主依赖容器，须含 ``search_service``（service 装配点延迟构造的
      SearchService）与可选 ``kb_repo``（缺省自建 KnowledgeBaseRepository）及 ``logger``
    - HostInternalSearchPort.search 签名与统一 ``SearchSourcePort`` 同形，天然满足
    """
    config = InternalSearchConfig(**(context.config or {}))
    kb_repo = context.deps.get("kb_repo") or KnowledgeBaseRepository(
        context.deps["session"]
    )
    return as_internal_search_port(
        search_port=context.deps["search_service"],
        kb_repo=kb_repo,
        space_id=context.space_id,
        user_id=context.user_id,
        internal_config=config,
        logger=context.deps.get("logger"),
    )


__all__ = [
    "HostInternalSearchPort",
    "as_internal_search_port",
    "build_internal_source",
]