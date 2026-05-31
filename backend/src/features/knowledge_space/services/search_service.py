"""
检索服务

处理知识库的向量检索、全文检索和混合检索
支持多租户和知识库层级
使用 Elasticsearch 统一向量和全文检索

注意: 分块数据仅存储在 Elasticsearch 中，不在 MySQL 中存储

模型配置支持：
- Embedding 模型：从知识库的 embedding_model 字段获取
- Rerank 模型：从请求的 rerank.model 字段获取
- 使用 ModelConfigService 获取凭证并创建客户端
"""

from typing import List, Optional, Dict, Any
import hashlib
import time

from sqlalchemy.ext.asyncio import AsyncSession

from src.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
from src.features.knowledge_space.repository.member_repository import MemberRepository
from src.features.knowledge_space.repository.space_repository import SpaceRepository
from src.shared.storage.elasticsearch_client import ElasticsearchClient
from src.shared.ai_models.embedding import BaseEmbedding, create_embedding_client
from src.shared.ai_models.rerank import BaseRerank, create_rerank_client
from src.shared.cache.redis_client import get_redis_client
from src.core.middleware.structured_logging import get_logger
from src.features.knowledge_space.api.exceptions import (
    SpaceNotFoundError,
    KnowledgeBaseNotFoundError,
    KnowledgeBaseAccessDeniedError,
    SpaceAccessDeniedError,
    SearchError,
    EmbeddingError,
    InvalidSearchModeError,
    InvalidSearchWeightError,
    KnowledgeSpaceError,
)
from src.features.knowledge_space.schemas.search_schema import (
    SEARCH_MODE_FALLBACK,
    SearchRequest,
    SearchResponse,
    SearchResult,
    LLMConfig,
    QueryRewriteConfig,
    MultimodalSearchRequest,
    MultimodalSearchMode,
)
from src.features.knowledge_space.models.knowledge_space import SpaceVisibility, KnowledgeSpace


# 默认配置常量
DEFAULT_SEARCH_CACHE_TTL = 3600  # 1 小时
DEFAULT_TOP_K = 10
DEFAULT_VECTOR_WEIGHT = 0.7
DEFAULT_BATCH_SIZE = 32


class SearchService:
    """
    检索服务

    使用 Elasticsearch 统一向量检索和全文检索
    支持多租户和知识库层级

    注意: 分块数据仅存储在 Elasticsearch 中

    模型配置支持：
    - Embedding 模型：从知识库的 embedding_model 字段获取
    - Rerank 模型：从请求的 rerank.model 字段获取
    - 使用 ModelConfigService 获取凭证并创建客户端
    """

    def __init__(
        self,
        session: AsyncSession,
        es_client: ElasticsearchClient,
        model_config_service: Optional[Any] = None,  # ModelConfigService
    ):
        self.session = session
        self.kb_repo = KnowledgeBaseRepository(session)
        self.member_repo = MemberRepository(session)
        self.space_repo = SpaceRepository(session)
        self.es_client = es_client
        self.model_config_service = model_config_service
        self.logger = get_logger(__name__)
        self._cache = None

    async def _get_cache(self):
        """获取 Redis 缓存客户端"""
        if self._cache is None:
            self._cache = await get_redis_client()
        return self._cache

    async def get_knowledge_base(self, kb_id: int):
        """获取知识库信息（公开方法，供路由层调用）"""
        return await self.kb_repo.get_by_id(kb_id)

    async def _get_embedding_client(
        self,
        user_id: int,
        model: str
    ) -> BaseEmbedding:
        """
        获取文本 Embedding 客户端

        通过 ModelConfigService 从数据库解析凭证，无配置时抛异常。

        Args:
            user_id: 用户 ID
            model: 模型名称

        Returns:
            Embedding 客户端

        Raises:
            EmbeddingError: 未找到模型配置
        """
        if self.model_config_service and model:
            try:
                return await self.model_config_service.get_embedding_client_by_model(
                    user_id, model
                )
            except Exception as e:
                raise EmbeddingError(f"获取 Embedding 客户端失败: {e}")

        # model 为 None 时，尝试获取默认模型
        if self.model_config_service:
            default_model = await self.model_config_service.get_default_model_name("embedding")
            if default_model:
                return await self.model_config_service.get_embedding_client_by_model(
                    user_id, default_model
                )

        raise EmbeddingError("未配置 Embedding 模型，请在模型配置中添加")

    async def _get_rerank_client(
        self,
        user_id: int,
        model: str
    ) -> Optional[BaseRerank]:
        """
        获取 Rerank 客户端

        通过 ModelConfigService 从数据库解析凭证

        Args:
            user_id: 用户 ID
            model: 模型名称

        Returns:
            Rerank 客户端，无配置时返回 None
        """
        if not model and self.model_config_service:
            model = await self.model_config_service.get_default_model_name("rerank")

        if self.model_config_service and model:
            return await self.model_config_service.get_rerank_client_by_model(
                user_id, model
            )

        return None

    async def _get_llm_client(
        self,
        user_id: int,
        model: str
    ) -> "BaseLLM":
        """
        获取 LLM 客户端

        通过 ModelConfigService 从数据库解析凭证

        Args:
            user_id: 用户 ID
            model: 模型名称

        Returns:
            LLM 客户端

        Raises:
            SearchError: 未找到模型配置
        """
        if not model and self.model_config_service:
            model = await self.model_config_service.get_default_model_name("llm")

        if self.model_config_service and model:
            return await self.model_config_service.get_llm_client_by_model(
                user_id, model
            )

        raise SearchError("未配置 LLM 模型，请在模型配置中添加")

    async def _generate_llm_answer(
        self,
        query: str,
        results: List[Dict[str, Any]],
        llm_config: LLMConfig,
        user_id: int,
    ) -> Dict[str, Any]:
        """
        使用 LLM 基于检索结果生成回答

        Args:
            query: 用户查询
            results: 检索结果
            llm_config: LLM 配置
            user_id: 用户 ID

        Returns:
            包含 answer, model, elapsed_ms 的字典
        """
        start_time = time.time()

        try:
            # 获取 LLM 客户端
            llm_client = await self._get_llm_client(user_id, llm_config.model)

            # 构建上下文
            context_parts = []
            for i, r in enumerate(results[:5], 1):  # 最多使用 Top 5 结果
                content = r.get("content", "")
                if content:
                    context_parts.append(f"[文档{i}]\n{content}")

            context = "\n\n".join(context_parts)

            # 构建提示词
            from src.shared.prompts.templates import PromptTemplate, PromptManager
            prompt = PromptManager.format_prompt(
                PromptTemplate.SEARCH_ANSWER.value,
                context=context,
                query=query,
            )

            # 调用 LLM 生成回答
            answer = await llm_client.generate_text(
                prompt=prompt,
                max_tokens=1024,
                temperature=llm_config.temperature,
                top_p=llm_config.top_p,
            )

            elapsed_ms = (time.time() - start_time) * 1000

            self.logger.info(
                "LLM 回答生成成功",
                model=llm_config.model,
                elapsed_ms=round(elapsed_ms, 2),
                answer_length=len(answer) if answer else 0,
            )

            return {
                "answer": answer,
                "model": llm_config.model,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            self.logger.error(
                "LLM 回答生成失败",
                query=query[:50],
                model=llm_config.model,
                error=str(e),
            )
            return {
                "answer": None,
                "answer_error": str(e),
                "model": llm_config.model,
                "elapsed_ms": elapsed_ms,
                "error": str(e),
            }

    async def _rewrite_query(
        self,
        query: str,
        rewrite_config: "QueryRewriteConfig",
        user_id: int,
    ) -> Dict[str, Any]:
        """
        查询改写

        支持两种策略：
        - hyde: 生成假设性文档，用于向量检索
        - sub_query: 拆分子问题，多路检索后合并

        Args:
            query: 原始查询文本
            rewrite_config: 查询改写配置
            user_id: 用户 ID

        Returns:
            {
                "search_query": 用于实际检索的查询文本（hyde 时为假设性文档）,
                "rewritten_queries": 返回给前端的改写问题列表,
                "sub_queries": sub_query 时的子问题列表（内部使用，用于多路检索）
            }
        """
        from src.shared.prompts.templates import PromptTemplate, PromptManager
        import json

        strategy = rewrite_config.strategy

        # 获取 LLM 客户端
        llm_model = rewrite_config.llm_model
        llm_client = await self._get_llm_client(user_id, llm_model)

        if strategy == "hyde":
            # HyDE: 生成假设性回答文档
            system_prompt = PromptManager.get_template(
                PromptTemplate.QUERY_REWRITE_HYDE_SYSTEM.value
            )
            user_prompt = PromptManager.format_prompt(
                PromptTemplate.QUERY_REWRITE_HYDE_USER.value,
                query=query,
            )

            hyde_document = await llm_client.generate_text(
                prompt=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=1024,
                temperature=0.3,
            )

            hyde_document = hyde_document.strip() if hyde_document else query

            self.logger.info(
                "HyDE 查询改写完成",
                original_query=query[:50],
                hyde_length=len(hyde_document),
            )

            return {
                "search_query": hyde_document,
                "rewritten_queries": [hyde_document],
                "sub_queries": None,
            }

        elif strategy == "sub_query":
            # Sub Query: 拆分子问题
            system_prompt = PromptManager.get_template(
                PromptTemplate.QUERY_REWRITE_SUB_QUERY_SYSTEM.value
            )
            user_prompt = PromptManager.format_prompt(
                PromptTemplate.QUERY_REWRITE_SUB_QUERY_USER.value,
                query=query,
                count=rewrite_config.sub_query_count,
            )

            response_text = await llm_client.generate_text(
                prompt=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=1024,
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            # 解析子问题列表
            sub_queries = []
            try:
                parsed = json.loads(response_text.strip())
                if isinstance(parsed, list):
                    sub_queries = [str(q).strip() for q in parsed if str(q).strip()]
                elif isinstance(parsed, dict):
                    # 兼容可能的 {"questions": [...]} 格式
                    for key in ("questions", "sub_queries", "queries"):
                        if key in parsed and isinstance(parsed[key], list):
                            sub_queries = [str(q).strip() for q in parsed[key] if str(q).strip()]
                            break
            except (json.JSONDecodeError, TypeError):
                # JSON 解析失败，尝试按行提取
                self.logger.warning("子问题 JSON 解析失败，尝试按行提取")
                for line in response_text.strip().split("\n"):
                    line = line.strip().strip("-").strip().strip('"').strip("'").strip()
                    if line and not line.startswith("[") and not line.startswith("]"):
                        sub_queries.append(line)

            if not sub_queries:
                self.logger.warning("子问题拆分为空，使用原始查询")
                sub_queries = [query]

            self.logger.info(
                "Sub Query 查询改写完成",
                original_query=query[:50],
                sub_query_count=len(sub_queries),
            )

            return {
                "search_query": query,  # sub_query 仍使用原始查询（仅用于 fallback）
                "rewritten_queries": sub_queries,
                "sub_queries": sub_queries,
            }

        return {
            "search_query": query,
            "rewritten_queries": None,
            "sub_queries": None,
        }

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
        import asyncio

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

        rrf_k = 60  # RRF 常数，论文推荐值

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
        rerank_enabled: bool = False,
        rerank_top_k: int = 3,
        rerank_model: str = "",
    ) -> str:
        """
        生成查询哈希（用于缓存键）

        包含所有影响检索结果的参数，包括 rerank 参数
        """
        normalized_query = query.strip().lower()
        key_content = (
            f"{normalized_query}:{top_k}:{search_type}:"
            f"{vector_weight:.2f}:{bm25_weight:.2f}:{content_weight:.2f}:{question_weight:.2f}:"
            f"rerank_{rerank_enabled}_{rerank_top_k}_{rerank_model}"
        )
        return hashlib.md5(key_content.encode('utf-8')).hexdigest()[:32]

    def _get_search_cache_key(self, kb_id: int, search_type: str, query_hash: str) -> str:
        """生成检索缓存键"""
        return f"search:{kb_id}:{search_type}:{query_hash}"

    async def _get_cached_search(self, cache_key: str) -> Optional[List[Dict[str, Any]]]:
        """获取缓存的检索结果"""
        try:
            cache = await self._get_cache()
            cached = await cache.get(cache_key)
            if cached is not None:
                self.logger.debug("检索缓存命中", cache_key=cache_key)
                return cached
        except KnowledgeSpaceError:
            raise
        except Exception as e:
            self.logger.warning("读取检索缓存失败", cache_key=cache_key, error=str(e))
        return None

    async def _cache_search_result(self, cache_key: str, results: List[Dict[str, Any]]) -> None:
        """缓存检索结果"""
        try:
            cache = await self._get_cache()
            await cache.set(cache_key, results, expire=DEFAULT_SEARCH_CACHE_TTL)
            self.logger.debug("检索结果已缓存", cache_key=cache_key, ttl=DEFAULT_SEARCH_CACHE_TTL)
        except KnowledgeSpaceError:
            raise
        except Exception as e:
            self.logger.warning("缓存检索结果失败", cache_key=cache_key, error=str(e))

    async def search(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        request: SearchRequest,
    ) -> Dict[str, Any]:
        """
        执行检索

        Args:
            space_id: 空间 ID
            kb_id: 知识库 ID
            user_id: 用户 ID
            request: 检索请求参数（SearchRequest schema）

        Returns:
            检索结果字典

        Raises:
            KnowledgeBaseNotFoundError: 知识库不存在
            KnowledgeBaseAccessDeniedError: 知识库不属于该空间
            SpaceAccessDeniedError: 无权限检索
            InvalidSearchModeError: 检索模式不可用
        """
        # 从 schema 中提取参数
        query = request.query
        search_mode = str(request.search_mode.value) if hasattr(request.search_mode, 'value') else str(request.search_mode)
        top_k = request.top_k
        fallback_on_unavailable = request.fallback_on_unavailable
        use_cache = request.use_cache
        score_threshold = request.score_threshold

        # 提取权重配置
        weights = request.weights
        vector_weight = weights.vector_weight if weights else 0.7
        bm25_weight = weights.bm25_weight if weights else 0.3
        content_weight = weights.content_weight if weights else 0.6
        question_weight = weights.question_weight if weights else 0.4
        rrf_k = weights.rrf_k if weights else 60

        # 校验算法权重：vector_weight + bm25_weight 必须等于 1.0
        if abs(vector_weight + bm25_weight - 1.0) > 0.01:
            raise InvalidSearchWeightError(
                vector_weight=vector_weight,
                bm25_weight=bm25_weight,
                reason=f"向量权重 ({vector_weight}) 与 BM25 权重 ({bm25_weight}) 之和必须等于 1.0，当前为 {vector_weight + bm25_weight}",
            )

        # 校验字段权重：content_weight + question_weight 必须等于 1.0（仅 all_* 模式）
        if search_mode.startswith("all_"):
            if abs(content_weight + question_weight - 1.0) > 0.01:
                raise InvalidSearchWeightError(
                    content_weight=content_weight,
                    question_weight=question_weight,
                    reason=f"内容权重 ({content_weight}) 与问题权重 ({question_weight}) 之和必须等于 1.0，当前为 {content_weight + question_weight}",
                )

        # 提取 rerank 配置
        rerank = request.rerank
        rerank_enabled = rerank.enabled if rerank else False
        rerank_top_k = rerank.top_k if rerank else 3
        rerank_model = rerank.model if rerank else "bge-reranker-v2-m3"
        start_time = time.time()
        original_mode = search_mode
        mode_fallback = False

        # 1. 验证知识库存在
        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb:
            raise KnowledgeBaseNotFoundError(kb_id)

        # 2. 防御性校验：验证 kb_id 归属指定的 space_id
        # 即使路由层已做校验，此处仍需防止绕过路由直接调用服务层
        if kb.space_id != space_id:
            raise KnowledgeBaseAccessDeniedError(
                kb_id=kb_id,
                user_id=user_id,
                reason="知识库不属于该空间",
            )

        # 3. 验证用户权限（检查是否是空间成员或空间是否公开）
        is_member = await self.member_repo.is_member(kb.space_id, user_id)
        if not is_member:
            space = await self.space_repo.get_by_id(kb.space_id, use_cache=True)
            if not space or space.visibility != SpaceVisibility.PUBLIC:
                raise SpaceAccessDeniedError(kb.space_id, user_id, "无权访问此知识库")

        # 4. 检查检索模式是否可用
        available_modes = kb.get_available_search_modes()
        if search_mode not in available_modes:
            if fallback_on_unavailable:
                # 自动降级
                search_mode = SEARCH_MODE_FALLBACK.get(search_mode, "content_hybrid")
                mode_fallback = True
                self.logger.warning(
                    "检索模式不可用，已自动降级",
                    original_mode=original_mode,
                    fallback_mode=search_mode,
                    kb_id=kb_id,
                )
            else:
                raise InvalidSearchModeError(
                    mode=search_mode,
                    available_modes=available_modes,
                    reason="知识库未启用问题生成功能",
                )

        # 4. 生成缓存键并尝试从缓存获取
        cache_key = None
        if use_cache:
            query_hash = self._generate_query_hash(
                query,
                top_k,
                search_mode,
                vector_weight,
                bm25_weight,
                content_weight,
                question_weight,
                rerank_enabled=rerank_enabled,
                rerank_top_k=rerank_top_k,
                rerank_model=rerank_model,
            )
            cache_key = self._get_search_cache_key(kb_id, search_mode, query_hash)
            cached_results = await self._get_cached_search(cache_key)
            if cached_results is not None:
                elapsed_ms = (time.time() - start_time) * 1000
                # 缓存命中时，LLM 回答需要单独生成（因为模型可能变化）
                answer = None
                answer_model = None
                answer_elapsed_ms = None
                answer_error = None

                llm_config = request.llm
                if llm_config and llm_config.enabled and cached_results:
                    try:
                        llm_result = await self._generate_llm_answer(
                            query=query,
                            results=cached_results,
                            llm_config=llm_config,
                            user_id=user_id,
                        )
                        answer = llm_result.get("answer")
                        answer_model = llm_result.get("model")
                        answer_elapsed_ms = llm_result.get("elapsed_ms")
                    except Exception as e:
                        self.logger.error(
                            "缓存命中但 LLM 回答生成异常",
                            error=str(e),
                        )
                        answer_error = str(e)

                response = {
                    "results": cached_results,
                    "total": len(cached_results),
                    "query": query,
                    "search_mode": search_mode,
                    "original_mode": original_mode if mode_fallback else None,
                    "mode_fallback": mode_fallback,
                    "top_k": top_k,
                    "elapsed_ms": elapsed_ms,
                    "cached": True,
                    "answer": answer,
                    "answer_model": answer_model,
                    "answer_elapsed_ms": answer_elapsed_ms,
                    "rewritten_queries": None,
                }
                if answer_error:
                    response["answer_error"] = answer_error
                return response

        # 5. 查询改写（如果配置了 query_rewrite）
        rewritten_queries = None
        rewrite_info = None
        if request.query_rewrite:
            try:
                rewrite_info = await self._rewrite_query(
                    query=query,
                    rewrite_config=request.query_rewrite,
                    user_id=user_id,
                )
                rewritten_queries = rewrite_info.get("rewritten_queries")
                self.logger.info(
                    "查询改写完成",
                    strategy=request.query_rewrite.strategy,
                    rewritten_count=len(rewritten_queries) if rewritten_queries else 0,
                )
            except Exception as e:
                self.logger.warning(
                    "查询改写失败，使用原始查询",
                    error=str(e),
                )

        # 6. 生成查询向量（如果需要）
        # HyDE 时使用假设性文档生成向量，sub_query 时使用原始查询
        effective_query = query
        if rewrite_info and rewrite_info.get("search_query"):
            effective_query = rewrite_info["search_query"]

        query_vector = None
        embedding_client = None
        if "vector" in search_mode or "hybrid" in search_mode:
            try:
                # 从空间获取 Embedding 模型（空间级别统一管理）
                space = await self.space_repo.get_by_id(kb.space_id, use_cache=True)
                embedding_model = space.embedding_model if space else None

                embedding_client = await self._get_embedding_client(user_id, embedding_model)
                query_vector = await embedding_client.generate_embedding(effective_query)

                self.logger.debug(
                    "生成查询向量成功",
                    embedding_model=embedding_model,
                    vector_dim=len(query_vector) if query_vector else 0,
                    is_rewritten=(effective_query != query),
                )
            except Exception as e:
                self.logger.error("生成查询向量失败", query=query[:50], error=str(e))
                raise EmbeddingError("生成查询向量失败，请稍后重试")

        # 7. 执行检索
        sub_queries = rewrite_info.get("sub_queries") if rewrite_info else None

        if sub_queries:
            # Sub Query 模式：对每个子问题分别检索，然后合并
            results = await self._search_with_sub_queries(
                space_id=space_id,
                kb_id=kb_id,
                search_mode=search_mode,
                sub_queries=sub_queries,
                query_vector=query_vector,
                top_k=top_k,
                vector_weight=vector_weight,
                bm25_weight=bm25_weight,
                content_weight=content_weight,
                question_weight=question_weight,
                rrf_k=rrf_k,
                merge_mode=request.query_rewrite.sub_query_merge_mode,
                embedding_client=embedding_client,
            )
        else:
            # 普通模式或 HyDE 模式：单次检索
            # HyDE 时用原始 query 做全文检索，用假设性文档向量做向量检索
            search_query = query  # BM25 仍使用原始查询
            search_vector = query_vector  # 向量使用改写后的（hyde 文档的 embedding）

            results = await self.es_client.search_by_mode(
                space_id=space_id,
                kb_id=kb_id,
                mode=search_mode,
                query=search_query,
                query_vector=search_vector,
                top_k=top_k,
                vector_weight=vector_weight,
                bm25_weight=bm25_weight,
                content_weight=content_weight,
                question_weight=question_weight,
                rrf_k=rrf_k,
            )

        # 8. 补充分块详情
        results = await self._enrich_results(results)

        # 9. 分数归一化（统一到 0~1 范围，使阈值跨模式一致）
        results = self._normalize_scores(results)

        # 10. 分数阈值过滤
        if score_threshold > 0.0:
            before_count = len(results)
            results = [r for r in results if r.get("score", 0) >= score_threshold]
            if before_count != len(results):
                self.logger.info(
                    "分数阈值过滤",
                    before=before_count,
                    after=len(results),
                    threshold=score_threshold,
                )

        # 11. Rerank 重排序
        if rerank_enabled and len(results) > 0:
            try:
                # 从请求中获取 rerank 模型名称
                rerank_client = await self._get_rerank_client(user_id, rerank_model)

                if rerank_client:
                    # 提取文档内容
                    documents = [r.get("content", "") for r in results]

                    self.logger.info(
                        "开始执行 Rerank 重排序",
                        rerank_model=rerank_model,
                        rerank_top_k=rerank_top_k,
                        document_count=len(documents),
                    )

                    rerank_results = await rerank_client.rerank(
                        query=query,
                        documents=documents,
                        top_k=min(rerank_top_k, len(results)),
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
                        rerank_enabled=rerank_enabled,
                    )

            except Exception as e:
                # Rerank 失败，降级返回原始结果
                self.logger.warning(
                    "Rerank 重排序失败，使用原始检索结果",
                    error=str(e),
                    rerank_model=rerank_model,
                    fallback_to_original=True,
                )

        # 12. 缓存结果
        if use_cache and cache_key and results:
            await self._cache_search_result(cache_key, results)

        # 13. LLM 回答生成（如果启用）
        answer = None
        answer_model = None
        answer_elapsed_ms = None
        answer_error = None

        llm_config = request.llm
        if llm_config and llm_config.enabled and results:
            try:
                llm_result = await self._generate_llm_answer(
                    query=query,
                    results=results,
                    llm_config=llm_config,
                    user_id=user_id,
                )
                answer = llm_result.get("answer")
                answer_model = llm_result.get("model")
                answer_elapsed_ms = llm_result.get("elapsed_ms")

                if llm_result.get("error"):
                    self.logger.warning(
                        "LLM 回答生成失败，仅返回检索结果",
                        error=llm_result.get("error"),
                    )
            except Exception as e:
                self.logger.error(
                    "LLM 回答生成异常",
                    error=str(e),
                )
                answer_error = str(e)

        elapsed_ms = (time.time() - start_time) * 1000

        response = {
            "results": results,
            "total": len(results),
            "query": query,
            "search_mode": search_mode,
            "original_mode": original_mode if mode_fallback else None,
            "mode_fallback": mode_fallback,
            "top_k": top_k,
            "elapsed_ms": elapsed_ms,
            "cached": False,
            "answer": answer,
            "answer_model": answer_model,
            "answer_elapsed_ms": answer_elapsed_ms,
            "rewritten_queries": rewritten_queries,
        }
        if answer_error:
            response["answer_error"] = answer_error
        return response

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
        分数归一化（Min-Max），统一到 0~1 范围

        不同检索模式的原始分数量纲差异巨大：
        - BM25: 0~30+
        - 向量(knn cosine): 0~1
        - RRF 融合: 0.005~0.05

        归一化后，用户设置的 score_threshold（0~1）在所有模式下都能正确生效

        Args:
            results: 检索结果列表

        Returns:
            归一化后的结果列表（原地修改 score 字段）
        """
        if not results:
            return results

        scores = [r.get("score", 0) for r in results]
        min_score = min(scores)
        max_score = max(scores)

        # 所有分数相同（只有一条结果或分数完全一致）时，归一化为 1.0
        score_range = max_score - min_score
        if score_range == 0:
            for r in results:
                r["original_score"] = r.get("score")
                # 所有分数相同时保留原始分数
            return results

        for r in results:
            original = r.get("score", 0)
            r["original_score"] = original
            r["score"] = round((original - min_score) / score_range, 4)

        return results

    async def invalidate_kb_search_cache(self, kb_id: int) -> None:
        """
        失效知识库的所有检索缓存

        Args:
            kb_id: 知识库 ID
        """
        try:
            cache = await self._get_cache()
            pattern = f"search:{kb_id}:*"
            total_deleted = await cache.delete_by_pattern(pattern, batch_size=100)
            self.logger.debug(
                "知识库检索缓存已清理",
                kb_id=kb_id,
                deleted=total_deleted,
            )
        except KnowledgeSpaceError:
            raise
        except Exception as e:
            self.logger.warning(
                "失效知识库检索缓存失败",
                kb_id=kb_id,
                error=str(e),
            )
            raise SearchError("失效知识库检索缓存失败，请稍后重试")

    async def get_available_modes(
        self,
        kb_id: int,
    ) -> List[str]:
        """
        获取知识库可用的检索模式

        Args:
            kb_id: 知识库 ID

        Returns:
            可用的检索模式列表

        Raises:
            KnowledgeBaseNotFoundError: 知识库不存在
        """
        # 验证知识库存在
        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb:
            raise KnowledgeBaseNotFoundError(kb_id)

        # 返回知识库配置的可用模式
        return kb.get_available_search_modes()

    async def _get_minio_client(self):
        """获取 MinIO 客户端"""
        from src.shared.clients import ClientFactory
        return await ClientFactory.get_minio_client()

    async def multimodal_search(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        request: MultimodalSearchRequest,
    ) -> SearchResponse:
        """
        统一多模态检索

        合并以文搜图和以图搜图为单一方法，支持 score 归一化。
        """
        import base64

        start_time = time.time()

        # 1. 校验空间和知识库
        space = await self._validate_space_and_kb(space_id, kb_id)

        # 2. 验证空间类型为 multimodal
        space_type = space.get_config().get("space_type", "text") if space else "text"
        if space_type != "multimodal":
            raise SearchError("多模态检索仅适用于多模态空间，请使用通用检索接口")

        # 3. 获取多模态嵌入客户端
        error_msg = "该空间未配置多模态嵌入模型，无法进行多模态检索"
        client, _ = await self._get_multimodal_client(space, user_id, error_msg)

        # 4. 生成查询向量
        if request.search_mode == MultimodalSearchMode.IMAGE_TO_IMAGE:
            image_bytes = base64.b64decode(request.image_base64)
            query_vector = await client.generate_image_embedding(image_bytes)
            effective_query = "[图片搜索]"
        else:
            query_vector = await client.generate_embedding(request.query)
            effective_query = request.query

        # 5. ES 检索
        raw_results = await self.es_client.image_vector_search(
            space_id=space_id,
            query_vector=query_vector,
            top_k=request.top_k,
            kb_id=kb_id,
        )

        # 6. 构建结果（threshold=0.0，过滤在归一化后）
        results = await self._build_image_search_results(raw_results, kb_id, 0.0)

        # 7. Score 归一化（Min-Max → 0~1）
        result_dicts = [
            {"score": r.score, "chunk_id": r.chunk_id, "content": r.content}
            for r in results
        ]
        self._normalize_scores(result_dicts)
        for r, d in zip(results, result_dicts):
            r.score = d["score"]

        # 8. 按 score_threshold 过滤（归一化后的分数）
        if request.score_threshold > 0:
            results = [r for r in results if r.score >= request.score_threshold]

        mode_str = "image_vector" if request.search_mode == MultimodalSearchMode.IMAGE_TO_IMAGE else "text_to_image"

        return SearchResponse(
            results=results,
            total=len(results),
            query=effective_query,
            search_mode=mode_str,
            original_mode=mode_str,
            top_k=request.top_k,
            elapsed_ms=round((time.time() - start_time) * 1000, 2),
        )

    # ---------- 图片搜索共享辅助方法 ----------

    async def _validate_space_and_kb(self, space_id: int, kb_id: int):
        """验证空间和知识库存在且关联，返回 space 对象"""
        space = await self.session.get(KnowledgeSpace, space_id)
        if not space:
            raise SpaceNotFoundError(space_id)
        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb or kb.space_id != space_id:
            raise KnowledgeBaseNotFoundError(kb_id)
        return space

    async def _get_multimodal_client(self, space, user_id: int, error_msg: str):
        """解析空间多模态嵌入配置，返回 (client, model_name)

        多模态空间从 config.embedding 读取，旧空间兼容 config.multimodal_embedding。
        """
        from src.shared.ai_models.embedding import BaseMultimodalEmbedding

        space_config = space.get_config()
        space_type = space_config.get("space_type", "text")

        if space_type == "multimodal":
            model_name = (space_config.get("embedding") or {}).get("model")
        else:
            mm_config = space_config.get("multimodal_embedding")
            model_name = mm_config.get("model") if mm_config else None

        if not model_name:
            raise EmbeddingError(error_msg)

        client = await self.model_config_service.get_multimodal_embedding_client_by_model(
            user_id, model_name
        )
        if not isinstance(client, BaseMultimodalEmbedding):
            raise ValueError(f"模型 {model_name} 不支持图片嵌入")

        return client, model_name

    async def _build_image_search_results(self, raw_results, kb_id: int, score_threshold: float):
        """从 ES 原始结果构建图片搜索结果列表"""
        results = []
        for hit in raw_results:
            # vector_search 返回 {"chunk_id": ..., "score": ..., "source": {...}}
            source = hit.get("source", {})
            score = hit.get("score", 0)
            if score_threshold > 0 and score < score_threshold:
                continue

            image_url = source.get("image_url", "")
            if image_url:
                try:
                    minio_client = await self._get_minio_client()
                    image_url = await minio_client.get_file_url(
                        minio_client.default_bucket, image_url, 3600
                    )
                except Exception as e:
                    self.logger.warning(
                        "图片 presigned URL 生成失败",
                        image_url=image_url,
                        error=str(e),
                    )
                    image_url = ""

            results.append(SearchResult(
                chunk_id=hit.get("chunk_id", ""),
                document_id=source.get("document_id", 0),
                kb_id=source.get("kb_id", kb_id),
                content=source.get("content", ""),
                score=score,
                chunk_index=source.get("chunk_index", 0),
                metadata=source.get("metadata"),
                file_info=source.get("file_info"),
                image_url=image_url,
                chunk_type=source.get("chunk_type", "image"),
            ))
        return results
