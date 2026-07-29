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

批次 2 接缝：``search`` 的**纯检索段**（缓存读写 / 向量生成 / ES 检索 / 归一化 / 阈值过滤 /
rerank）已委托给 ``RetrievalEngine.retrieve_raw``（见 ``retrieval_engine.py``）。本服务保留
宿主业务：权限 / 多租户校验、模式可用性 + fallback、查询改写（LLM）、模型客户端解析、
LLM 回答生成、响应组装。响应 dict 键与旧路径逐字一致。

回滚：``NOVAMIND_LEGACY_RETRIEVAL=1`` 走 ``_search_legacy``（旧内联编排，复用引擎 helper）。
"""

from typing import List, Optional, Dict, Any
import os
import time

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.repository.space_repository import SpaceRepository
from novamind.shared.storage.elasticsearch_client import ElasticsearchClient
from novamind.shared.ai_models.embedding import BaseEmbedding
from novamind.shared.ai_models.rerank import BaseRerank
from novamind.shared.ai_models.base_model import BaseLLM
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.api.exceptions import (
    KnowledgeBaseNotFoundError,
    KnowledgeBaseAccessDeniedError,
    SpaceAccessDeniedError,
    SearchError,
    EmbeddingError,
    InvalidSearchModeError,
    InvalidSearchWeightError,
)
from novamind.features.knowledge_space.schemas.search_schema import (
    SEARCH_MODE_FALLBACK,
    SearchRequest,
    LLMConfig,
    QueryRewriteConfig,
)
from novamind.features.knowledge_space.models.knowledge_space import SpaceVisibility
from novamind.features.knowledge_space.services.retrieval_engine import (
    RetrievalEngine,
    RetrievalQuery,
)


# 默认配置常量
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
        retrieval_engine: Optional[RetrievalEngine] = None,
    ):
        self.session = session
        self.kb_repo = KnowledgeBaseRepository(session)
        self.member_repo = MemberRepository(session)
        self.space_repo = SpaceRepository(session)
        self.es_client = es_client
        self.model_config_service = model_config_service
        self.logger = get_logger(__name__)
        self._retrieval_engine = retrieval_engine

    @property
    def retrieval_engine(self) -> RetrievalEngine:
        """延迟获取检索引擎（构造函数中不强制要求）"""
        if self._retrieval_engine is None:
            self._retrieval_engine = RetrievalEngine(self.es_client, self.logger)
        return self._retrieval_engine

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

        # model 为 None 时，尝试获取用户默认模型
        if self.model_config_service:
            default_model = await self.model_config_service.get_user_default_model_name(user_id, "embedding")
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
            model = await self.model_config_service.get_user_default_model_name(user_id, "rerank")

        if self.model_config_service and model:
            return await self.model_config_service.get_rerank_client_by_model(
                user_id, model
            )

        return None

    async def _get_llm_client(
        self,
        user_id: int,
        model: str
    ) -> BaseLLM:
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
            model = await self.model_config_service.get_user_default_model_name(user_id, "llm")

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
            from novamind.shared.prompts.templates import PromptManager
            from novamind.shared.prompts.sanitize import sanitize_prompt_input
            # 净化用户 query，剥离 markdown 标题/分隔标签，降低 prompt 注入风险
            safe_query = sanitize_prompt_input(query)
            prompt = PromptManager.format_prompt(
                "search_answer",
                context=context,
                query=safe_query,
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
        from novamind.shared.prompts.templates import PromptManager
        import json

        strategy = rewrite_config.strategy

        # 获取 LLM 客户端
        llm_model = rewrite_config.llm_model
        llm_client = await self._get_llm_client(user_id, llm_model)

        if strategy == "hyde":
            # HyDE: 生成假设性回答文档
            system_prompt = PromptManager.get_template(
                "query_rewrite_hyde_system"
            )
            user_prompt = PromptManager.format_prompt(
                "query_rewrite_hyde_user",
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
                "query_rewrite_sub_query_system"
            )
            user_prompt = PromptManager.format_prompt(
                "query_rewrite_sub_query_user",
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
        # 回滚开关：NOVAMIND_LEGACY_RETRIEVAL=1 走旧内联编排
        if os.getenv("NOVAMIND_LEGACY_RETRIEVAL") == "1":
            return await self._search_legacy(space_id, kb_id, user_id, request)
        return await self._search_via_engine(space_id, kb_id, user_id, request)

    async def _search_via_engine(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        request: SearchRequest,
    ) -> Dict[str, Any]:
        """新路径：宿主做权限/配置/改写/生成，纯检索委托 RetrievalEngine.retrieve_raw。"""
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
        # 仅 hybrid 模式实际使用这两个权重；纯 BM25/vector 模式不消费，跳过校验避免误拒
        if "hybrid" in search_mode and abs(vector_weight + bm25_weight - 1.0) > 0.01:
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
        rerank_model = rerank.model if rerank else None
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

        # 5. 查询改写（如果配置了 query_rewrite）—— LLM，留宿主
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

        effective_query = query
        if rewrite_info and rewrite_info.get("search_query"):
            effective_query = rewrite_info["search_query"]
        sub_queries = rewrite_info.get("sub_queries") if rewrite_info else None
        sub_query_merge_mode = (
            request.query_rewrite.sub_query_merge_mode
            if (sub_queries and request.query_rewrite) else "rrf"
        )

        # 6. 客户端 resolver（懒解析：engine 仅在非缓存命中 / 有结果时才调用，
        #    逐字对齐原 search 的懒解析时序——缓存命中不解析 embedding，避免配置缺失误报）
        needs_vector = "vector" in search_mode or "hybrid" in search_mode
        embedding_client_resolver = None
        if needs_vector:
            async def _resolve_embedding() -> Optional[BaseEmbedding]:
                space = await self.space_repo.get_by_id(kb.space_id, use_cache=True)
                embedding_model = space.embedding_model if space else None
                return await self._get_embedding_client(user_id, embedding_model)
            embedding_client_resolver = _resolve_embedding
        rerank_client_resolver = None
        if rerank_enabled:
            async def _resolve_rerank() -> Optional[BaseRerank]:
                return await self._get_rerank_client(user_id, rerank_model)
            rerank_client_resolver = _resolve_rerank

        # 7. 构造纯检索入参并委托引擎
        rq = RetrievalQuery(
            space_id=space_id,
            kb_id=kb_id,
            query=query,
            effective_query=effective_query,
            sub_queries=sub_queries,
            sub_query_merge_mode=sub_query_merge_mode,
            search_mode=search_mode,
            top_k=top_k,
            vector_weight=vector_weight,
            bm25_weight=bm25_weight,
            content_weight=content_weight,
            question_weight=question_weight,
            rrf_k=rrf_k,
            score_threshold=score_threshold,
            rerank_enabled=rerank_enabled,
            rerank_top_k=rerank_top_k,
            rerank_model=rerank_model,
        )
        # query_rewrite 改写结果非确定，不入缓存——启用改写时跳过缓存读写
        use_cache_for_engine = use_cache and request.query_rewrite is None
        result = await self.retrieval_engine.retrieve_raw(
            rq,
            embedding_client_resolver=embedding_client_resolver,
            rerank_client_resolver=rerank_client_resolver,
            use_cache=use_cache_for_engine,
        )

        # 8. LLM 回答生成 + elapsed_ms 保真
        # 缓存命中：elapsed_ms 在 LLM 前算（对齐旧路径 L732）
        # 缓存未命中：先 LLM 后 elapsed_ms（对齐旧路径 L981）
        answer = None
        answer_model = None
        answer_elapsed_ms = None
        answer_error = None
        llm_config = request.llm

        if result.cached:
            elapsed_ms = (time.time() - start_time) * 1000
            if llm_config and llm_config.enabled and result.results:
                try:
                    llm_result = await self._generate_llm_answer(
                        query=query,
                        results=result.results,
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
        else:
            if llm_config and llm_config.enabled and result.results:
                try:
                    llm_result = await self._generate_llm_answer(
                        query=query,
                        results=result.results,
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
            "results": result.results,
            "total": len(result.results),
            "query": query,
            "search_mode": search_mode,
            "original_mode": original_mode if mode_fallback else None,
            "mode_fallback": mode_fallback,
            "top_k": top_k,
            "elapsed_ms": elapsed_ms,
            "cached": result.cached,
            "answer": answer,
            "answer_model": answer_model,
            "answer_elapsed_ms": answer_elapsed_ms,
            "rewritten_queries": rewritten_queries,
        }
        if answer_error:
            response["answer_error"] = answer_error
        return response

    async def _search_legacy(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        request: SearchRequest,
    ) -> Dict[str, Any]:
        """旧内联编排（NOVAMIND_LEGACY_RETRIEVAL=1 时使用，保留作回滚）。

        与批次 2 前的 search() 逐字等价：权限/模式/改写/向量/检索/enrich/归一化/阈值/rerank/
        缓存/LLM 全在一个方法内。纯检索 helper（_search_with_sub_queries / _generate_query_hash /
        _enrich_results / _normalize_scores / 缓存读写）已迁至 RetrievalEngine，此处通过
        self.retrieval_engine 复用（helper 为逐字搬迁，行为不变）。
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
        if "hybrid" in search_mode and abs(vector_weight + bm25_weight - 1.0) > 0.01:
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
        rerank_model = rerank.model if rerank else None
        start_time = time.time()
        original_mode = search_mode
        mode_fallback = False

        # 1. 验证知识库存在
        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb:
            raise KnowledgeBaseNotFoundError(kb_id)

        # 2. 防御性校验：验证 kb_id 归属指定的 space_id
        if kb.space_id != space_id:
            raise KnowledgeBaseAccessDeniedError(
                kb_id=kb_id,
                user_id=user_id,
                reason="知识库不属于该空间",
            )

        # 3. 验证用户权限
        is_member = await self.member_repo.is_member(kb.space_id, user_id)
        if not is_member:
            space = await self.space_repo.get_by_id(kb.space_id, use_cache=True)
            if not space or space.visibility != SpaceVisibility.PUBLIC:
                raise SpaceAccessDeniedError(kb.space_id, user_id, "无权访问此知识库")

        # 4. 检查检索模式是否可用
        available_modes = kb.get_available_search_modes()
        if search_mode not in available_modes:
            if fallback_on_unavailable:
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
        engine = self.retrieval_engine
        cache_key = None
        # query_rewrite 改写结果非确定；启用改写时直接跳过缓存读写
        if use_cache and request.query_rewrite is None:
            query_hash = engine._generate_query_hash(
                query,
                top_k,
                search_mode,
                vector_weight,
                bm25_weight,
                content_weight,
                question_weight,
                rrf_k=rrf_k,
                rerank_enabled=rerank_enabled,
                rerank_top_k=rerank_top_k,
                rerank_model=rerank_model,
                score_threshold=score_threshold,
                query_rewrite_sig="none",
            )
            cache_key = engine._get_search_cache_key(kb_id, search_mode, query_hash)
            cached_results = await engine._get_cached_search(cache_key)
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
            results = await engine._search_with_sub_queries(
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
        results = await engine._enrich_results(results)

        # 9. 分数归一化
        results = engine._normalize_scores(results)

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
                rerank_client = await self._get_rerank_client(user_id, rerank_model)

                if rerank_client:
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

                    reranked_results = []
                    for rerank_item in rerank_results:
                        original_index = rerank_item["index"]
                        original_result = results[original_index].copy()

                        original_result["original_score"] = results[original_index].get("score")
                        original_result["score"] = rerank_item["relevance_score"]
                        original_result["reranked"] = True

                        reranked_results.append(original_result)

                    results = reranked_results
                    results = engine._normalize_scores(results)

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
                self.logger.warning(
                    "Rerank 重排序失败，使用原始检索结果",
                    error=str(e),
                    rerank_model=rerank_model,
                    fallback_to_original=True,
                )

        # 12. 缓存结果
        if use_cache and cache_key and results:
            await engine._cache_search_result(cache_key, results)

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

    async def invalidate_kb_search_cache(self, kb_id: int) -> None:
        """
        失效知识库的所有检索缓存（委托 RetrievalEngine）

        Args:
            kb_id: 知识库 ID
        """
        await self.retrieval_engine.invalidate_kb_search_cache(kb_id)

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
        from novamind.shared.clients import ClientFactory
        return await ClientFactory.get_minio_client()