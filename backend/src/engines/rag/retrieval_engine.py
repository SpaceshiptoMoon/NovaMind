"""检索引擎（纯检索段）—— ``novamind.engines.rag`` 核心组件。

批次 2 接缝：把 ``SearchService.search`` 中与宿主业务（权限 / 多租户 / 模型配置 / LLM 生成）
无关的**纯检索段**抽离为 ``RetrievalEngine.retrieve_raw``。引擎只持有 ``es_client`` + logger +
中立 ``CachePort``（宿主装配点注入，未注入时缓存 no-op 降级），**不持有** session / repos /
ModelConfigService；``embedding_client`` / ``rerank_client`` 由宿主通过 resolver 回调按需注入
（懒解析，逐字复刻原 ``search`` 的懒解析时序：缓存命中时不解析 embedding，避免配置缺失误报
``EmbeddingError``）。

批次 6a-2 去 feature 边：异常改用中立 ``engines.rag.errors``
（``RagError``/``EmbeddingError``/``SearchError``，不依赖宿主 ``BaseAPIError``）；
缓存改用中立 ``engines.rag.cache_port.CachePort``（构造器注入，删 ``shared.cache.redis_client``
直接 import）。宿主 ``SearchService`` 在装配点捕获中立异常重抛为宿主 ``api.exceptions`` 同名异常，
保留宿主异常码契约（400）不变。

批次 6x 归位 ``engines/rag/``：引擎按目录分层独立于 features，host 经
``from novamind.engines.rag import RetrievalEngine, RetrievalQuery`` 导入。
``NOVAMIND_LEGACY_RETRIEVAL=1`` 时 ``SearchService.search`` 走旧内联路径（旧路径保留）。
"""
from typing import Any, Awaitable, Callable, Dict, List, Optional
import asyncio
import hashlib

from novamind.shared.ai_models.embedding import BaseEmbedding
from novamind.shared.ai_models.rerank import BaseRerank
from novamind.engines.rag.cache_port import CachePort
from novamind.shared.logging import get_logger
from novamind.engines.rag.errors import RagError, EmbeddingError, SearchError

# 默认配置常量（与 search_service 保持一致，批次 6 迁入引擎包）
DEFAULT_SEARCH_CACHE_TTL = 3600  # 1 小时

# 检索客户端 resolver 类型：宿主按需构造并返回客户端（懒解析）
EmbeddingClientResolver = Callable[[], Awaitable[Optional[BaseEmbedding]]]
RerankClientResolver = Callable[[], Awaitable[Optional[BaseRerank]]]


class RetrievalResult:
    """``retrieve_raw`` 返回值：仅含检索结果列表 + 是否命中缓存。

    其余响应字段（query / total / search_mode / elapsed_ms / answer / rewritten_queries 等）
    由宿主 ``SearchService`` 组装，引擎不感知。
    """

    __slots__ = ("results", "cached")

    def __init__(self, results: List[Dict[str, Any]], cached: bool) -> None:
        self.results = results
        self.cached = cached


class RetrievalQuery:
    """纯检索入参（宿主从 ``SearchRequest`` + 改写结果构造后注入）。

    把所有影响纯检索结果的字段集中为一个对象，避免 ``retrieve_raw`` 出现 15+ 个关键字参数。
    引擎不依赖宿主的 ``SearchRequest`` schema，这是端口边界。
    """

    __slots__ = (
        "space_id",
        "kb_id",
        "query",
        "effective_query",
        "sub_queries",
        "sub_query_merge_mode",
        "search_mode",
        "top_k",
        "vector_weight",
        "bm25_weight",
        "content_weight",
        "question_weight",
        "rrf_k",
        "score_threshold",
        "rerank_enabled",
        "rerank_top_k",
        "rerank_model",
    )

    def __init__(
        self,
        *,
        space_id: int,
        kb_id: int,
        query: str,
        effective_query: str,
        sub_queries: Optional[List[str]],
        sub_query_merge_mode: str,
        search_mode: str,
        top_k: int,
        vector_weight: float,
        bm25_weight: float,
        content_weight: float,
        question_weight: float,
        rrf_k: int,
        score_threshold: float,
        rerank_enabled: bool,
        rerank_top_k: int,
        rerank_model: Optional[str],
    ) -> None:
        self.space_id = space_id
        self.kb_id = kb_id
        self.query = query
        self.effective_query = effective_query
        self.sub_queries = sub_queries
        self.sub_query_merge_mode = sub_query_merge_mode
        self.search_mode = search_mode
        self.top_k = top_k
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight
        self.content_weight = content_weight
        self.question_weight = question_weight
        self.rrf_k = rrf_k
        self.score_threshold = score_threshold
        self.rerank_enabled = rerank_enabled
        self.rerank_top_k = rerank_top_k
        self.rerank_model = rerank_model


class RetrievalEngine:
    """纯检索引擎：缓存读写 + 向量生成 + ES 检索 + 归一化 + 阈值过滤 + rerank。

    不做权限校验、不碰 ORM、不调 LLM、不感知 ModelConfigService。客户端由宿主按需注入。
    """

    def __init__(
        self,
        es_client: Any,
        logger: Optional[Any] = None,
        cache_port: Optional[CachePort] = None,
    ) -> None:
        self.es_client = es_client
        self.logger = logger or get_logger(__name__)
        # 中立缓存端口：宿主装配点注入 HostCachePort（包 shared.cache.redis_client）。
        # 未注入（None）时缓存读写一律 no-op 降级。_cache 惰性解析为 cache_port 实例，
        # 保留旧接缝测试可直接注入 _cache 的能力。
        self._cache_port = cache_port
        self._cache = None

    async def _get_cache(self) -> Optional[CachePort]:
        """惰性解析缓存端口实例。

        优先返回直接注入的 ``_cache``（接缝测试路径）；否则绑定构造器传入的
        ``cache_port``；两者皆空返回 ``None``（无缓存，调用方负责 no-op 降级）。
        """
        if self._cache is None:
            self._cache = self._cache_port
        return self._cache

    async def retrieve_raw(
        self,
        q: RetrievalQuery,
        *,
        embedding_client_resolver: Optional[EmbeddingClientResolver] = None,
        rerank_client_resolver: Optional[RerankClientResolver] = None,
        use_cache: bool = True,
    ) -> RetrievalResult:
        """执行纯检索段，返回 ``RetrievalResult``。

        顺序逐字复刻原 ``SearchService.search`` 的纯检索段：
        缓存读 → 向量生成 → ES 检索(单查询 / 子查询) → enrich → 归一化 → 阈值过滤
        → rerank → 缓存写。

        ``use_cache`` 由宿主决定：仅当 ``use_cache and request.query_rewrite is None``
        时传 True（改写检索非确定，不入缓存）。缓存键内 ``query_rewrite_sig`` 恒为 "none"
        （能进缓存的请求本就没有改写）。
        """
        # 1. 缓存读（仅 use_cache 时；宿主保证此时 query_rewrite 为 None）
        cache_key = None
        if use_cache:
            query_hash = self._generate_query_hash(
                q.query,
                q.top_k,
                q.search_mode,
                q.vector_weight,
                q.bm25_weight,
                q.content_weight,
                q.question_weight,
                rrf_k=q.rrf_k,
                rerank_enabled=q.rerank_enabled,
                rerank_top_k=q.rerank_top_k,
                rerank_model=q.rerank_model or "",
                score_threshold=q.score_threshold,
                query_rewrite_sig="none",
            )
            cache_key = self._get_search_cache_key(q.kb_id, q.search_mode, query_hash)
            cached_results = await self._get_cached_search(cache_key)
            if cached_results is not None:
                # 缓存命中：不解析 embedding/rerank，直接返回（逐字对齐原 L730-732 早返回）
                return RetrievalResult(cached_results, cached=True)

        # 2. 生成查询向量（vector / hybrid 模式才需要）
        # HyDE 时 effective_query 为假设性文档；sub_query 时为原始查询（仅作 fallback）
        query_vector = None
        embedding_client = None
        if "vector" in q.search_mode or "hybrid" in q.search_mode:
            try:
                if embedding_client_resolver is None:
                    raise EmbeddingError("未提供 Embedding 客户端 resolver")
                embedding_client = await embedding_client_resolver()
                if embedding_client is None:
                    raise EmbeddingError("未配置 Embedding 模型，请在模型配置中添加")
                query_vector = await embedding_client.generate_embedding(q.effective_query)
                self.logger.debug(
                    "生成查询向量成功",
                    vector_dim=len(query_vector) if query_vector else 0,
                    is_rewritten=(q.effective_query != q.query),
                )
            except Exception as e:
                self.logger.error("生成查询向量失败", query=q.query[:50], error=str(e))
                raise EmbeddingError("生成查询向量失败，请稍后重试")

        # 3. 执行检索
        if q.sub_queries:
            # Sub Query 模式：对每个子问题分别检索，然后合并
            results = await self._search_with_sub_queries(
                space_id=q.space_id,
                kb_id=q.kb_id,
                search_mode=q.search_mode,
                sub_queries=q.sub_queries,
                query_vector=query_vector,
                top_k=q.top_k,
                vector_weight=q.vector_weight,
                bm25_weight=q.bm25_weight,
                content_weight=q.content_weight,
                question_weight=q.question_weight,
                rrf_k=q.rrf_k,
                merge_mode=q.sub_query_merge_mode,
                embedding_client=embedding_client,
            )
        else:
            # 普通模式或 HyDE 模式：单次检索
            # HyDE 时用原始 query 做全文检索，用假设性文档向量做向量检索
            results = await self.es_client.search_by_mode(
                space_id=q.space_id,
                kb_id=q.kb_id,
                mode=q.search_mode,
                query=q.query,  # BM25 仍使用原始查询
                query_vector=query_vector,  # 向量使用改写后的（hyde 文档的 embedding）
                top_k=q.top_k,
                vector_weight=q.vector_weight,
                bm25_weight=q.bm25_weight,
                content_weight=q.content_weight,
                question_weight=q.question_weight,
                rrf_k=q.rrf_k,
            )

        # 4. 补充分块详情
        results = await self._enrich_results(results)

        # 5. 分数归一化（统一到 0~1，使阈值跨模式一致）
        results = self._normalize_scores(results)

        # 6. 分数阈值过滤
        if q.score_threshold > 0.0:
            before_count = len(results)
            results = [r for r in results if r.get("score", 0) >= q.score_threshold]
            if before_count != len(results):
                self.logger.info(
                    "分数阈值过滤",
                    before=before_count,
                    after=len(results),
                    threshold=q.score_threshold,
                )

        # 7. Rerank 重排序
        if q.rerank_enabled and len(results) > 0:
            try:
                if rerank_client_resolver is None:
                    raise SearchError("未提供 Rerank 客户端 resolver")
                rerank_client = await rerank_client_resolver()

                if rerank_client:
                    # 提取文档内容
                    documents = [r.get("content", "") for r in results]

                    self.logger.info(
                        "开始执行 Rerank 重排序",
                        rerank_model=q.rerank_model,
                        rerank_top_k=q.rerank_top_k,
                        document_count=len(documents),
                    )

                    rerank_results = await rerank_client.rerank(
                        query=q.query,
                        documents=documents,
                        top_k=min(q.rerank_top_k, len(results)),
                    )

                    # 根据 rerank 结果重新排序并更新分数
                    reranked_results = []
                    for rerank_item in rerank_results:
                        original_index = rerank_item["index"]
                        original_result = results[original_index].copy()

                        # 保留原始分数，用 rerank 分数替换
                        original_result["original_score"] = results[original_index].get("score")
                        original_result["score"] = rerank_item["relevance_score"]
                        original_result["reranked"] = True

                        reranked_results.append(original_result)

                    results = reranked_results

                    # Rerank 后重新归一化分数到 0~1
                    results = self._normalize_scores(results)

                    self.logger.info(
                        "Rerank 重排序完成",
                        original_count=len(documents),
                        reranked_count=len(reranked_results),
                        top_score=reranked_results[0]["score"] if reranked_results else 0,
                    )
                else:
                    self.logger.warning(
                        "Rerank 客户端未初始化（全局配置未启用），跳过重排序",
                        rerank_enabled=q.rerank_enabled,
                    )

            except Exception as e:
                # Rerank 失败，降级返回原始结果
                self.logger.warning(
                    "Rerank 重排序失败，使用原始检索结果",
                    error=str(e),
                    rerank_model=q.rerank_model,
                    fallback_to_original=True,
                )

        # 8. 缓存结果
        if use_cache and cache_key and results:
            await self._cache_search_result(cache_key, results)

        return RetrievalResult(results, cached=False)

    async def _search_with_sub_queries(
        self,
        space_id: int,
        kb_id: int,
        search_mode: str,
        sub_queries: List[str],
        query_vector: Optional[List[float]],
        top_k: int,
        vector_weight: float = 0.7,
        bm25_weight: float = 0.3,
        content_weight: float = 0.6,
        question_weight: float = 0.4,
        rrf_k: int = 60,
        merge_mode: str = "rrf",
        embedding_client: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Sub Query 多路检索并合并结果

        对每个子问题分别执行检索，然后按指定策略合并结果

        Args:
            space_id: 空间 ID
            kb_id: 知识库 ID
            search_mode: 检索模式
            sub_queries: 子问题列表
            query_vector: 原始查询向量（作为回退）
            top_k: 每个子问题的返回数量
            vector_weight/bm25_weight/content_weight/question_weight/rrf_k: 权重参数
            merge_mode: 合并方式 - rrf(加权融合) / score(分数取最大)
            embedding_client: 嵌入客户端（为每个子问题独立生成向量）

        Returns:
            合并后的检索结果列表
        """
        per_query_top_k = max(top_k, 5)  # 每个子问题至少返回 5 个
        needs_vector = "vector" in search_mode or "hybrid" in search_mode

        # 并行执行所有子问题的检索
        async def search_one(sub_query: str) -> List[Dict[str, Any]]:
            # 为每个子问题独立生成向量，提升向量检索精度
            sub_vector = query_vector
            if needs_vector and embedding_client:
                try:
                    sub_vector = await embedding_client.generate_embedding(sub_query)
                except Exception as e:
                    self.logger.warning(
                        "子问题向量生成失败，使用原始查询向量",
                        sub_query=sub_query[:50],
                        error=str(e),
                    )

            return await self.es_client.search_by_mode(
                space_id=space_id,
                kb_id=kb_id,
                mode=search_mode,
                query=sub_query,
                query_vector=sub_vector,
                top_k=per_query_top_k,
                vector_weight=vector_weight,
                bm25_weight=bm25_weight,
                content_weight=content_weight,
                question_weight=question_weight,
                rrf_k=rrf_k,
            )

        all_results = await asyncio.gather(
            *[search_one(sq) for sq in sub_queries],
            return_exceptions=True,
        )

        # 过滤异常结果
        valid_results = []
        for i, r in enumerate(all_results):
            if isinstance(r, Exception):
                self.logger.warning(
                    "子问题检索失败",
                    sub_query=sub_queries[i][:50],
                    error=str(r),
                )
            elif r:
                valid_results.append(r)

        if not valid_results:
            return []

        # 按 chunk_id 去重并合并分数
        chunk_data: Dict[str, Dict[str, Any]] = {}
        # RRF 融合：记录每个文档在每个子查询结果中的排名
        chunk_rrf_scores: Dict[str, float] = {}
        # score 模式：记录原始分数
        chunk_scores: Dict[str, List[float]] = {}

        # rrf_k 使用形参(来自用户 weights.rrf_k 配置)，不再硬编码覆盖

        for result_list in valid_results:
            for rank, item in enumerate(result_list, start=1):
                chunk_id = item.get("chunk_id")
                if not chunk_id:
                    continue
                if chunk_id not in chunk_data:
                    chunk_data[chunk_id] = item
                    chunk_rrf_scores[chunk_id] = 0.0
                    chunk_scores[chunk_id] = []
                # 累加标准 RRF 分数: 1/(k+rank)
                chunk_rrf_scores[chunk_id] += 1.0 / (rrf_k + rank)
                chunk_scores[chunk_id].append(item.get("score", 0.0))

        # 计算合并分数
        merged_results = []
        for chunk_id in chunk_data:
            if merge_mode == "score":
                # 取最高分
                merged_score = max(chunk_scores[chunk_id])
            else:
                # 标准 RRF 融合分数
                merged_score = chunk_rrf_scores[chunk_id]

            result = chunk_data[chunk_id].copy()
            result["score"] = merged_score
            merged_results.append(result)

        # 按分数降序排序，截取 top_k
        merged_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return merged_results[:top_k]

    @staticmethod
    def _generate_query_hash(
        query: str,
        top_k: int,
        search_type: str,
        vector_weight: float = 0.7,
        bm25_weight: float = 0.3,
        content_weight: float = 0.6,
        question_weight: float = 0.4,
        rrf_k: int = 60,
        rerank_enabled: bool = False,
        rerank_top_k: int = 3,
        rerank_model: str = "",
        score_threshold: float = 0.0,
        query_rewrite_sig: str = "",
    ) -> str:
        """
        生成查询哈希（用于缓存键）

        包含所有影响检索结果的参数：权重（含 rrf_k）、rerank、score_threshold、query_rewrite 签名。
        rrf_k 影响 RRF 融合排名，必须入键，否则改 rrf_k 会命中旧缓存；
        score_threshold 影响结果过滤；query_rewrite 改写实际检索 query，必须入键，
        否则仅阈值或改写配置不同的请求会共享缓存，导致跨配置缓存污染。
        """
        normalized_query = query.strip().lower()
        key_content = (
            f"{normalized_query}:{top_k}:{search_type}:"
            f"{vector_weight:.2f}:{bm25_weight:.2f}:{content_weight:.2f}:{question_weight:.2f}:"
            f"rrf_{rrf_k}:"
            f"rerank_{rerank_enabled}_{rerank_top_k}_{rerank_model}:"
            f"st_{score_threshold:.4f}:qw_{query_rewrite_sig}"
        )
        return hashlib.md5(key_content.encode('utf-8')).hexdigest()[:32]

    def _get_search_cache_key(self, kb_id: int, search_type: str, query_hash: str) -> str:
        """生成检索缓存键"""
        return f"search:{kb_id}:{search_type}:{query_hash}"

    async def _get_cached_search(self, cache_key: str) -> Optional[List[Dict[str, Any]]]:
        """获取缓存的检索结果"""
        try:
            cache = await self._get_cache()
            if cache is None:
                return None
            cached = await cache.get(cache_key)
            if cached is not None:
                self.logger.debug("检索缓存命中", cache_key=cache_key)
                return cached
        except RagError:
            raise
        except Exception as e:
            self.logger.warning("读取检索缓存失败", cache_key=cache_key, error=str(e))
        return None

    async def _cache_search_result(self, cache_key: str, results: List[Dict[str, Any]]) -> None:
        """缓存检索结果"""
        try:
            cache = await self._get_cache()
            if cache is None:
                return
            await cache.set(cache_key, results, expire=DEFAULT_SEARCH_CACHE_TTL)
            self.logger.debug("检索结果已缓存", cache_key=cache_key, ttl=DEFAULT_SEARCH_CACHE_TTL)
        except RagError:
            raise
        except Exception as e:
            self.logger.warning("缓存检索结果失败", cache_key=cache_key, error=str(e))

    async def _enrich_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        补充检索结果详情

        由于分块数据仅存储在 Elasticsearch 中，直接从 ES 结果中提取信息

        Args:
            results: ES 检索结果

        Returns:
            补充后的结果
        """
        if not results:
            return results

        # 直接从 ES 结果中提取信息，不需要查询 MySQL
        enriched_results = []
        for r in results:
            source = r.get("source", {})
            file_info = source.get("file_info", {})

            enriched = {
                "chunk_id": r.get("chunk_id") or source.get("chunk_id"),
                "score": r.get("score"),
                "content": source.get("content", ""),
                "document_id": source.get("document_id"),
                "chunk_index": source.get("chunk_index"),
                "kb_id": source.get("kb_id"),
                "metadata": source.get("metadata", {}),
                "file_info": file_info,
                "questions": source.get("questions"),
            }

            enriched_results.append(enriched)

        return enriched_results

    @staticmethod
    def _normalize_scores(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        分数归一化，统一到 0~1 范围

        不同检索模式的原始分数量纲差异巨大：
        - BM25: 0~30+
        - 向量(knn cosine): 0~1
        - RRF 融合: 0.005~0.05

        采用 max 归一化（score / max_score）：最高分映射到 1.0，其余按比例缩放。
        相比 Min-Max，最低分不会被强制降到 0 而被任意正阈值误杀——score_threshold 的
        语义稳定为「相对最高分的比例」（如 0.5 = 至少达到最高分的一半）。所有分数相等
        时统一归一化为 1.0（视为同等相关，阈值不再误杀）。

        Args:
            results: 检索结果列表

        Returns:
            归一化后的结果列表（原地修改 score 字段）
        """
        if not results:
            return results

        scores = [r.get("score", 0) for r in results]
        max_score = max(scores)

        # 最高分 <= 0（全为 0 或负）时统一归一化为 1.0，视为同等相关，避免除零与阈值误杀
        if max_score <= 0:
            for r in results:
                r["original_score"] = r.get("score")
                r["score"] = 1.0
            return results

        for r in results:
            original = r.get("score", 0)
            r["original_score"] = original
            r["score"] = round(original / max_score, 4)

        return results

    async def invalidate_kb_search_cache(self, kb_id: int) -> None:
        """
        失效知识库的所有检索缓存

        Args:
            kb_id: 知识库 ID
        """
        try:
            cache = await self._get_cache()
            if cache is None:
                return
            pattern = f"search:{kb_id}:*"
            total_deleted = await cache.delete_by_pattern(pattern, batch_size=100)
            self.logger.debug(
                "知识库检索缓存已清理",
                kb_id=kb_id,
                deleted=total_deleted,
            )
        except RagError:
            raise
        except Exception as e:
            self.logger.warning(
                "失效知识库检索缓存失败",
                kb_id=kb_id,
                error=str(e),
            )
            raise SearchError("失效知识库检索缓存失败，请稍后重试")