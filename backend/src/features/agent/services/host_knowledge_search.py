"""HostKnowledgeSearchPort 宿主适配器：为 agent 引擎提供空间/知识库发现与检索。
跨 feature 走 knowledge_space 公共面（R2）：权限走 access_service，发现/检索走 services 公共方法，不触碰对方 repository。
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
        """懒取 ES 客户端并在实例内缓存，后续调用复用。"""
        if self._es_client is None:
            from novamind.shared.storage.client_factory import get_elasticsearch_client

            self._es_client = await get_elasticsearch_client()
        return self._es_client

    async def _build_search_service(self) -> Any:
        """组装带运营埋点的检索服务（db + ES + 模型配置）。

        Agent 知识工具是用户触发的检索消费方，用 InstrumentedSearchService
        让 query 进 kb-ops 事件账本。
        """
        from novamind.features.knowledge_space.services.instrumented_search_service import (
            InstrumentedSearchService,
        )

        es_client = await self._get_es_client()
        return InstrumentedSearchService(self._db, es_client, self._mcs)

    def _space_service(self) -> Any:
        """构造 SpaceService（跨 feature 只走公共面，函数内懒 import 防环）。"""
        from novamind.features.knowledge_space.services.space_service import (
            SpaceService,
        )

        return SpaceService(self._db)

    def _kb_service(self) -> Any:
        """构造 KnowledgeBaseService（仅 KB 发现面使用，minio/es 传 None）。"""
        from novamind.features.knowledge_space.services.knowledge_base_service import (
            KnowledgeBaseService,
        )

        return KnowledgeBaseService(self._db, es_client=None, minio_client=None)

    def _doc_query_service(self) -> Any:
        """构造 DocumentQueryService（仅 KB 文档查询面使用，minio/es 传 None）。"""
        from novamind.features.knowledge_space.services.document_query_service import (
            DocumentQueryService,
        )

        # list_documents 只走 KB 文档查询面（doc repo），minio/es 未用到，传 None
        return DocumentQueryService(self._db, minio_client=None, es_client=None)

    # ==================== 权限校验 ====================

    async def can_access_space(self, space_id: int, user_id: int) -> bool:
        """空间级访问判定，委托 knowledge_space 权限中心。

        Args:
            space_id: 空间主键 ID。
            user_id: 当前用户 ID。

        Returns:
            该用户可访问该空间时为 True。
        """
        from novamind.features.knowledge_space.services.access_service import (
            check_space_access,
        )

        return await check_space_access(self._db, space_id, user_id)

    # ==================== 空间与知识库发现 ====================

    async def list_spaces(self, user_id: int) -> list[SpaceInfo]:
        """列出用户可访问的空间，映射为引擎侧 SpaceInfo。

        Args:
            user_id: 当前用户 ID。

        Returns:
            SpaceInfo 列表（id/名称/描述）。
        """
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
        """列出空间下 ACTIVE 状态的知识库，映射为引擎侧 KbInfo。

        Args:
            space_id: 空间主键 ID。
            user_id: 当前用户 ID。

        Returns:
            KbInfo 列表（id/名称/space_id/描述）。
        """
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
        """遍历用户全部空间汇总 ACTIVE 知识库，附带所属空间名。

        Args:
            user_id: 当前用户 ID。

        Returns:
            KbInfo 列表，额外携带 space_name 字段。
        """
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
        """按模式检索知识库内容；指定 kb_id 单库检索，缺省时取空间前 3 个 KB 跨库检索按分数合并取 top_k；单库失败静默跳过。

        Args:
            space_id: 空间主键 ID。
            user_id: 当前用户 ID。
            query: 检索查询文本。
            top_k: 返回条数上限，默认 5。
            search_mode: 检索模式（内容/混合等），默认 CONTENT_HYBRID。
            kb_id: 限定单库检索的知识库 ID；None 跨库检索。
            score_threshold: 分数阈值；None 时按 0 处理即不过滤。

        Returns:
            按分数排序的 KnowledgeSearchItem 列表（content/score/document_id/chunk_id 等）。
        """
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
            # kb_id 缺省：空间下活跃 KB 跨库检索取前 3 个合并。
            # 归档库不参与召回；显式指定归档 kb_id 的由 SearchService 拦截。
            from novamind.features.knowledge_space.models.knowledge_base import (
                KnowledgeBaseStatus,
            )

            kbs = await self._kb_service().get_space_knowledge_bases(
                space_id, status=KnowledgeBaseStatus.ACTIVE
            )
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
        """分页列出知识库文档并返回总数，映射为引擎侧 DocumentListResult。

        Args:
            space_id: 空间主键 ID。
            kb_id: 知识库主键 ID。
            user_id: 当前用户 ID。
            page: 页码，从 1 起，默认 1。
            page_size: 页大小，默认 20。

        Returns:
            含 total 与文档列表（id/文件名）的 DocumentListResult。

        Raises:
            ValueError: KB 不存在或不属于该空间（与检索层同款防御：不区分两种
                情形，防借 space A 的访问权枚举 space B 的 KB 文档——IDOR）。
        """
        from novamind.features.knowledge_space.repository.knowledge_base_repository import (
            KnowledgeBaseRepository,
        )

        kb = await KnowledgeBaseRepository(self._db).get_by_id(kb_id)
        if not kb or kb.space_id != space_id:
            raise ValueError(f"知识库 {kb_id} 不存在或不属于空间 {space_id}")

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

    # ==================== 检索管线（QA 管线吸收，批2） ====================

    async def pipeline_search(
        self,
        space_id: int,
        user_id: int,
        query: str,
        *,
        llm_client: Any | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        rewrite_strategy: str = "completion",
        grade_retry_enabled: bool = False,
        grade_passing_score: int = 5,
        score_threshold: float = 0.3,
        top_k: int = 5,
        search_mode: str = SearchMode.CONTENT_HYBRID.value,
        kb_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """带质量保障层的知识库检索管线：改写 → 检索 → grade-retry（可选）→ 阈值过滤。

        吸收 QA ai_chat_service 的检索管线语义（工作台统一对话面批2），差异点：
        - 改写/打分 LLM 由调用方注入（agent 会话模型），修掉 QA「改写固定用用户默认
          模型」的错位；llm_client=None 时改写与 grade 静默降级（能力缺失非错误结果）。
        - 拒答语义变为结果声明 ``insufficient_evidence``，由主模型决定如何向用户表达
          （QA 侧是服务端固定文案拒答，agent 场景主模型自持）。
        - 检索执行仍走 InstrumentedSearchService，kb-ops 事件账本埋点不回退。

        Args:
            space_id: 空间主键 ID（调用方已校验访问权限）。
            user_id: 当前用户 ID。
            query: 检索查询文本（用户原话）。
            llm_client: 会话模型 LLM 客户端；None 跳过改写与 grade。
            conversation_history: 对话历史（OpenAI 格式），completion 改写消费。
            rewrite_strategy: 改写策略；"none" 关闭改写。
            grade_retry_enabled: 是否启用检索后打分重试（切模式+降阈值）。
            grade_passing_score: 打分及格线（1-10）。
            score_threshold: 低分过滤线；None 传给检索层即不过滤。
            top_k: 返回条数上限。
            search_mode: 首轮检索模式。
            kb_ids: 限定知识库列表；None 跨空间前 3 个活跃库。

        Returns:
            dict：items（KnowledgeSearchItem 列表）、rewritten_query（实际检索用词）、
            rewrite_degraded、grade_traces、insufficient_evidence（过滤后为空且曾
            有原始结果时 True）、raw_count（过滤前数量）。
        """
        from novamind.features.knowledge_space.schemas.search_schema import SearchRequest

        # ===== 1. 查询改写（会话模型；失败降级原 query） =====
        rewritten = query
        rewrite_degraded = False
        # decompose 拆出的多个子查询逐条检索合并（此前只取首个子查询，其余丢弃）
        rewritten_queries: list[str] = [query]
        if rewrite_strategy != "none" and llm_client is not None:
            from novamind.engines.rag.query_rewriter import QueryRewriter, RewriteStrategy

            rewriter = QueryRewriter(llm_client)
            try:
                result = await rewriter.rewrite(
                    query=query,
                    strategy=RewriteStrategy(rewrite_strategy),
                    history=conversation_history or [],
                )
                if result.queries:
                    rewritten = result.queries[0]
                    rewritten_queries = [q for q in result.queries if str(q).strip()]
                rewrite_degraded = result.degraded
            except Exception:
                rewrite_degraded = True

        search_service = await self._build_search_service()

        async def _do_search(mode: str, threshold: float | None) -> list[dict[str, Any]]:
            """单轮检索：多子查询逐条检索按 chunk_id 去重保最高分合并；kb_ids 限库，
            否则跨空间活跃库前 3 合并；单库失败静默跳过。"""
            best: dict[str, dict[str, Any]] = {}
            for sub_q in rewritten_queries:
                request = SearchRequest(
                    query=sub_q,
                    search_mode=mode,
                    top_k=top_k,
                    score_threshold=threshold if threshold is not None else 0.0,
                )
                if kb_ids:
                    kb_targets: list[int] = list(kb_ids)
                else:
                    from novamind.features.knowledge_space.models.knowledge_base import (
                        KnowledgeBaseStatus,
                    )

                    kbs = await self._kb_service().get_space_knowledge_bases(
                        space_id, status=KnowledgeBaseStatus.ACTIVE
                    )
                    kb_targets = [kb.id for kb in kbs[:3]]
                for kbid in kb_targets:
                    try:
                        r = await search_service.search(
                            space_id=space_id, kb_id=kbid,
                            user_id=user_id, request=request,
                        )
                    except Exception:
                        continue
                    for hit in r.get("results", []):
                        key = str(hit.get("chunk_id") or hit.get("content", ""))[:200]
                        prev = best.get(key)
                        if prev is None or (hit.get("score", 0) or 0) > (prev.get("score", 0) or 0):
                            best[key] = hit
            merged = sorted(best.values(), key=lambda x: x.get("score", 0), reverse=True)
            return merged[:top_k]

        # ===== 2. 检索（grade-retry 可选：不通过切模式+降阈值重试） =====
        grade_traces: list[dict[str, Any]] = []
        if grade_retry_enabled and llm_client is not None:
            from novamind.engines.rag import GradeRetrier

            retrier = GradeRetrier(
                llm_client,
                prompt_provider=self._build_prompt_provider(),
                logger=self._build_logger(),
            )
            fallback_modes = [
                SearchMode.CONTENT_HYBRID.value,
                SearchMode.CONTENT_VECTOR.value,
                SearchMode.CONTENT_BM25.value,
            ]
            raw_results = await self._grade_retry_search(
                retrier, rewritten, search_mode, fallback_modes,
                score_threshold, grade_passing_score, _do_search, grade_traces,
            )
        else:
            raw_results = await _do_search(search_mode, score_threshold)

        raw_count = len(raw_results)

        # ===== 3. 阈值过滤 + 结果映射 =====
        # 过滤已在 SearchRequest 下推（检索层预过滤），此处兜底双保险（对齐 QA post-hoc 语义）
        if score_threshold is not None:
            raw_results = [r for r in raw_results if r.get("score", 0) >= score_threshold]

        items = [
            KnowledgeSearchItem(
                content=r.get("content", ""),
                score=r.get("score", 0),
                document_id=r.get("document_id"),
                chunk_id=r.get("chunk_id"),
                file_info=r.get("file_info"),
            )
            for r in raw_results
        ]

        return {
            "items": items,
            "rewritten_query": rewritten,
            "rewrite_degraded": rewrite_degraded,
            "grade_traces": grade_traces,
            "insufficient_evidence": raw_count > 0 and len(items) == 0,
            "raw_count": raw_count,
        }

    async def _grade_retry_search(
        self,
        retrier: Any,
        query: str,
        initial_mode: str,
        fallback_modes: list[str],
        score_threshold: float,
        passing_score: int,
        do_search: Any,
        grade_traces: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """GradeRetrier 适配：search_fn 签名对齐（返回 (sources, system_prompt)），只回收 sources。

        grade_traces 由 retrier 产出后追加进传入列表，供工具结果透传给前端轨迹。
        """
        result_sources, _, traces = await retrier.search_with_retry(
            query=query,
            search_fn=lambda q, mode, threshold: self._search_fn_adapter(
                do_search, mode, threshold
            ),
            search_modes=fallback_modes,
            initial_mode=initial_mode,
            score_threshold=score_threshold,
            passing_score=passing_score,
        )
        grade_traces.extend(traces)
        return result_sources

    @staticmethod
    async def _search_fn_adapter(
        do_search: Any, mode: str, threshold: float | None
    ) -> tuple[list[dict[str, Any]], str]:
        """把单轮检索函数适配成 GradeRetrier 期望的 (sources, system_prompt) 返回形态。"""
        sources = await do_search(mode, threshold)
        return sources, ""

    def _build_prompt_provider(self) -> Any:
        """构造 PromptManager（grade 打分 prompt 从中央注册表取，与 QA 同源）。"""
        from novamind.shared.prompts.prompt_manager import PromptManager

        return PromptManager()

    @staticmethod
    def _build_logger() -> Any:
        """构造管线日志器（结构化 JSON 日志口径）。"""
        from novamind.core.middleware.structured_logging import get_logger

        return get_logger(__name__)
