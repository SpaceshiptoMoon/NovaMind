"""
Elasticsearch 客户端封装

提供统一的向量存储和全文检索功能
每个知识空间使用独立的索引
"""

import asyncio
import re
from typing import Any

from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch import ConnectionError as ESConnectionError
from novamind.shared.logging import get_logger
from novamind.shared.storage.index_schema import DefaultIndexSchema, IndexSchema

logger = get_logger(__name__)

# 最大搜索结果限制（防止资源耗尽）
MAX_SEARCH_RESULTS = 100

# Elasticsearch 查询特殊字符（需要转义）
ES_SPECIAL_CHARS = re.compile(r'[+\-=&|><!(){}[\]^"~*?:\\/]')


class ElasticsearchClient:
    """
    Elasticsearch 客户端

    每个知识空间使用独立的索引
    """

    def __init__(
        self,
        hosts: list[str],
        username: str | None = None,
        password: str | None = None,
        use_ssl: bool = False,
        verify_certs: bool = True,
        ca_certs: str | None = None,
        default_embedding_dim: int = 1024,
        default_analyzer: str = "standard",
        index_schema: IndexSchema | None = None,
    ):
        """归一 host 协议（按 use_ssl 强制 http/https 前缀一致）并构建带超时与重试的 AsyncElasticsearch 客户端。"""
        self.verify_certs = verify_certs
        self.ca_certs = ca_certs
        self.default_embedding_dim = default_embedding_dim
        self.default_analyzer = default_analyzer
        # 索引命名/mapping/字段名经 schema 注入；默认实现逐字复刻旧版行为
        self._schema: IndexSchema = index_schema or DefaultIndexSchema()

        if use_ssl:
            resolved_hosts = [
                h.replace("http://", "https://") if h.startswith("http://") else h
                for h in hosts
            ]
        else:
            resolved_hosts = [
                h.replace("https://", "http://") if h.startswith("https://") else h
                for h in hosts
            ]
        self.hosts = resolved_hosts

        es_kwargs = dict(
            verify_certs=verify_certs,
            ca_certs=ca_certs,
            request_timeout=30,
            max_retries=3,
            retry_on_timeout=True,
        )
        if username and password:
            self.es_client = AsyncElasticsearch(
                hosts=resolved_hosts,
                basic_auth=(username, password),
                **es_kwargs,
            )
        else:
            self.es_client = AsyncElasticsearch(
                hosts=resolved_hosts,
                **es_kwargs,
            )

        logger.info("Elasticsearch 客户端初始化成功", hosts=hosts)

    # ========== 健康检查 ==========

    async def ping(self) -> bool:
        """探活集群连通性；异常记 error 并返回 False（不抛）。"""
        try:
            return await self.es_client.ping()
        except Exception as e:
            logger.error("Elasticsearch 连接检查失败", error=str(e))
            return False

    async def close(self) -> None:
        """关闭底层 ES 连接（应用关闭期调用）。"""
        await self.es_client.close()
        logger.info("Elasticsearch 客户端已关闭")

    # ========== 索引管理 ==========

    def generate_index_name(self, space_id: int) -> str:
        """生成空间索引名称（经 schema）。

        Args:
            space_id: 空间 ID。

        Returns:
            索引名字符串（默认 schema 为 space_{space_id}）。
        """
        return self._schema.index_name(space_id)

    async def index_exists(self, space_id: int) -> bool:
        """探测空间索引是否已创建。

        Args:
            space_id: 空间 ID。

        Returns:
            索引存在返回 True；探测异常记 error 并返回 False。
        """
        index_name = self.generate_index_name(space_id)
        try:
            return bool(await self.es_client.indices.exists(index=index_name))
        except Exception as e:
            logger.error("检查索引失败", index=index_name, error=str(e))
            return False

    async def create_index(
        self,
        space_id: int,
        embedding_dim: int | None = None,
        analyzer: str | None = None,
    ) -> bool:
        """创建空间索引（幂等：索引已存在时直接返回成功）。

        Args:
            space_id: 空间 ID。
            embedding_dim: 向量维度；None 用客户端默认维度。
            analyzer: 检索分词器（如 ik_max_word）；None 用客户端默认。

        Returns:
            创建成功或已存在返回 True。

        Raises:
            Exception: 创建失败且非已存在类错误时原样抛出。
        """
        index_name = self.generate_index_name(space_id)
        dim = embedding_dim or self.default_embedding_dim
        _analyzer = analyzer or self.default_analyzer

        # mapping/settings 经 schema 构造（逐字复刻旧版 properties）
        body = self._schema.build_create_body(dim, _analyzer)

        try:
            await self.es_client.indices.create(
                index=index_name,
                settings=body["settings"],
                mappings=body["mappings"],
            )
            logger.info("创建索引成功", index=index_name, embedding_dim=dim)
            return True
        except Exception as e:
            error_str = str(e)
            if "resource_already_exists_exception" in error_str:
                logger.info("索引已存在，跳过创建", index=index_name)
                return True
            logger.error("创建索引失败", index=index_name, error=error_str)
            raise

    async def ensure_index_exists(
        self, space_id: int, embedding_dim: int | None = None
    ) -> str:
        """确保索引存在（不存在则按给定维度创建）。

        Args:
            space_id: 空间 ID。
            embedding_dim: 向量维度；None 用客户端默认维度。

        Returns:
            索引名字符串。
        """
        index_name = self.generate_index_name(space_id)
        if not await self.index_exists(space_id):
            await self.create_index(space_id, embedding_dim)
        return index_name

    async def delete_index(self, space_id: int) -> bool:
        """整索引删除（危险操作：空间内全部分块一并消失）。

        Args:
            space_id: 空间 ID。

        Returns:
            删除成功或索引本不存在返回 True；其他失败返回 False。
        """
        index_name = self.generate_index_name(space_id)
        try:
            await self.es_client.indices.delete(index=index_name)
            logger.info("删除索引成功", index=index_name)
            return True
        except Exception as e:
            error_str = str(e)
            if "index_not_found_exception" in error_str:
                logger.info("索引不存在，跳过删除", index=index_name)
                return True
            logger.error("删除索引失败", index=index_name, error=error_str)
            return False

    async def delete_kb_chunks(self, space_id: int, kb_id: int) -> int:
        """删除空间索引中指定知识库的所有文档。

        Args:
            space_id: 空间 ID。
            kb_id: 知识库 ID。

        Returns:
            实际删除的分块数（异常降级返回 0）。
        """
        index_name = self.generate_index_name(space_id)
        try:
            result = await self.es_client.delete_by_query(
                index=index_name,
                body={"query": {"term": {self._schema.field_names.kb_id: kb_id}}},
            )
            deleted = result.get("deleted", 0)
            logger.info("删除知识库文档成功", index=index_name, kb_id=kb_id, deleted=deleted)
            return deleted
        except Exception as e:
            logger.error("删除知识库文档失败", index=index_name, kb_id=kb_id, error=str(e))
            return 0

    # ========== 文档操作 ==========

    async def index_chunk(self, space_id: int, chunk_data: dict[str, Any]) -> bool:
        """索引单个分块（按 chunk_id 作为文档 _id 写入）。

        Args:
            space_id: 空间 ID。
            chunk_data: 分块数据 dict，须含 chunk_id 键；embedding_dim 键可选用于建索引。

        Returns:
            写入成功返回 True；失败记 error 返回 False。
        """
        index_name = await self.ensure_index_exists(
            space_id, embedding_dim=chunk_data.get("embedding_dim")
        )
        try:
            await self.es_client.index(
                index=index_name, id=chunk_data["chunk_id"], document=chunk_data
            )
            return True
        except Exception as e:
            logger.error("索引分块失败", chunk_id=chunk_data.get("chunk_id"), error=str(e))
            return False

    async def bulk_index_chunks(
        self,
        space_id: int,
        chunks: list[dict[str, Any]],
        embedding_dim: int | None = None,
    ) -> int:
        """批量索引分块（bulk 写入，逐条统计成败）。

        Args:
            space_id: 空间 ID。
            chunks: 分块 dict 列表，每项须含 chunk_id 键。
            embedding_dim: 向量维度；必须显式传入（不兜底、不从向量长度推断），缺失即抛错。

        Returns:
            成功写入的分块数（整体异常降级返回 0）。

        Raises:
            RuntimeError: embedding_dim 为 None（维度缺失会让索引维度不可追踪）。
        """
        if not chunks:
            return 0

        # embedding_dim 必须由调用方显式传入（来源于 space.embedding_config["dimension"]，
        # 由 space_service 从模型 extra_config.dimension 回填）。不做任何兜底——既不
        # 静默降级 default_embedding_dim(1024)，也不从向量长度推断。兜底会让索引维度
        # 不可追踪，且与真实向量维度不符时 bulk 全部失败。维度缺失即显式抛错，要求
        # 在模型配置中补齐 dimension 或重新保存空间配置触发自动回填。
        if embedding_dim is None:
            raise RuntimeError(
                "无法确定 embedding 维度：space.embedding_config[\"dimension\"] 未配置，"
                "请在模型配置中补齐该模型的 dimension，或重新保存空间配置以触发自动回填"
            )

        index_name = await self.ensure_index_exists(
            space_id, embedding_dim=embedding_dim
        )
        actions = []
        for chunk in chunks:
            actions.append({"index": {"_index": index_name, "_id": chunk["chunk_id"]}})
            actions.append(chunk)

        try:
            result = await self.es_client.bulk(operations=actions)
            success = len(
                [
                    r
                    for r in result.get("items", [])
                    if r.get("index", {}).get("status") in (200, 201)
                ]
            )
            errors = [
                r for r in result.get("items", [])
                if r.get("index", {}).get("status") not in (200, 201)
            ]
            if errors:
                logger.error(
                    "批量索引部分失败",
                    index=index_name,
                    success=success,
                    failed=len(errors),
                    first_error=errors[0] if errors else None,
                )
            else:
                logger.info("批量索引分块成功", index=index_name, count=success)
            return success
        except Exception as e:
            logger.error("批量索引分块失败", index=index_name, error=str(e))
            return 0

    async def get_chunk(self, space_id: int, chunk_id: str) -> dict[str, Any] | None:
        """按 chunk_id 读取分块原文；不存在或异常均返回 None。

        Args:
            space_id: 空间 ID。
            chunk_id: 分块 ID（即 ES 文档 _id）。

        Returns:
            分块 _source dict；未找到或读取失败返回 None。
        """
        index_name = self.generate_index_name(space_id)
        try:
            result = await self.es_client.get(index=index_name, id=chunk_id)
            if result.get("found"):
                return result["_source"]
            return None
        except Exception as e:
            logger.error("获取分块失败", chunk_id=chunk_id, error=str(e))
            return None

    async def delete_chunk(self, space_id: int, chunk_id: str) -> bool:
        """按 chunk_id 删除单个分块（异常降级返回 False）。

        Args:
            space_id: 空间 ID。
            chunk_id: 分块 ID（即 ES 文档 _id）。

        Returns:
            删除成功返回 True。
        """
        index_name = self.generate_index_name(space_id)
        try:
            await self.es_client.delete(index=index_name, id=chunk_id)
            return True
        except Exception as e:
            logger.error("删除分块失败", chunk_id=chunk_id, error=str(e))
            return False

    async def delete_document_chunks(self, space_id: int, document_id: int) -> int:
        """delete_by_query 清空文档全部分块，返回实际删除数。

        Args:
            space_id: 空间 ID。
            document_id: 文档 ID。

        Returns:
            实际删除的分块数（异常降级返回 0）。
        """
        index_name = self.generate_index_name(space_id)
        try:
            result = await self.es_client.delete_by_query(
                index=index_name, body={"query": {"term": {self._schema.field_names.document_id: document_id}}}
            )
            return result.get("deleted", 0)
        except Exception as e:
            logger.error("删除文档分块失败", document_id=document_id, error=str(e))
            return 0

    async def get_document_chunks(
        self, space_id: int, document_id: int, skip: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        """获取文档的分块（分页），返回 ``{"items": [...], "total": int}``。

        ``total`` 来自 ES ``track_total_hits``，用于前端分页控件；不再返回全量分块。
        """
        index_name = self.generate_index_name(space_id)
        try:
            result = await self.es_client.search(
                index=index_name,
                query={"term": {self._schema.field_names.document_id: document_id}},
                from_=skip,
                size=limit,
                sort=[{self._schema.field_names.chunk_index: {"order": "asc"}}],
                track_total_hits=True,
            )
            hits = result.get("hits", {})
            total_obj = hits.get("total", 0)
            if isinstance(total_obj, dict):
                total_value = int(total_obj.get("value", 0))
            else:
                total_value = int(total_obj or 0)
            items = [
                {"chunk_id": hit["_id"], "score": hit["_score"], **hit["_source"]}
                for hit in hits.get("hits", [])
            ]
            return {"items": items, "total": total_value}
        except Exception as e:
            logger.error("获取文档分块失败", document_id=document_id, error=str(e))
            return {"items": [], "total": 0}

    # ========== 搜索辅助 ==========

    def _build_kb_filter(self, kb_id: int | None = None) -> list[dict]:
        """构建知识库过滤条件 + 文档生命周期排除式过滤（kb-ops B1）。

        排除式而非白名单式（must lifecycle_status=active）：存量 chunk 无该字段，
        must_not terms 对 missing 字段不命中 → 自动视为可召回，零回填；
        白名单式会把全部存量 chunk 一刀切出检索（误杀）。
        """
        filters: list[dict] = []
        if kb_id is not None:
            filters.append({"term": {self._schema.field_names.kb_id: kb_id}})
        filters.append({
            "bool": {
                "must_not": [
                    {"terms": {"lifecycle_status": ["superseded", "archived"]}}
                ]
            }
        })
        return filters

    # ========== 搜索功能 ==========

    async def vector_search(
        self, space_id: int, query_vector: list[float], top_k: int = 5,
        kb_id: int | None = None,
        field: str | None = None,
        chunk_type_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """向量相似度搜索（统一入口，支持 embedding 字段）。

        Args:
            space_id: 空间 ID。
            query_vector: 查询向量。
            top_k: 返回条数上限（自动截断到 MAX_SEARCH_RESULTS）。
            kb_id: 知识库过滤；None 表示不过滤。
            field: 向量字段名；None 用 schema 默认 embedding 字段。
            chunk_type_filter: 分块类型过滤（如 wiki_page）；None 表示不过滤。

        Returns:
            结果列表，每项含 chunk_id、score、source（分块原文 dict）；失败返回空表。

        Raises:
            elasticsearch.ConnectionError: ES 连接类基础设施异常原样抛出（不静默吞）。
        """
        top_k = min(top_k, MAX_SEARCH_RESULTS)
        index_name = self.generate_index_name(space_id)
        # 字段名经 schema 解析；默认 embedding 字段
        field = field or self._schema.field_names.embedding
        filters = self._build_kb_filter(kb_id)
        if chunk_type_filter:
            filters.append({"term": {self._schema.field_names.chunk_type: chunk_type_filter}})

        try:
            knn_query = {
                "field": field,
                "query_vector": query_vector,
                "k": top_k,
                "num_candidates": top_k * 3,
            }
            if filters:
                knn_query["filter"] = {"bool": {"filter": filters}}

            result = await self.es_client.search(
                index=index_name,
                size=top_k,
                knn=knn_query,
            )
            return [
                {
                    "chunk_id": hit["_id"],
                    "score": hit["_score"],
                    "source": hit["_source"],
                }
                for hit in result.get("hits", {}).get("hits", [])
            ]
        except NotFoundError:
            return []
        except ESConnectionError as e:
            logger.error("ES 搜索异常（基础设施问题）", index=index_name, error=str(e))
            raise
        except Exception as e:
            logger.warning("向量搜索失败", index=index_name, error=str(e))
            return []

    @staticmethod
    def _escape_query(query: str) -> str:
        """转义查询串中的 ES 保留字符，防特殊字符破坏 query_string 语法。"""
        if not query:
            return ""
        return ES_SPECIAL_CHARS.sub(r"\\\g<0>", query)

    async def _execute_search(
        self, index_name: str, body: dict, log_label: str, top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """通用搜索执行：查询 ES → 结果解析 → 异常处理"""
        try:
            result = await self.es_client.search(index=index_name, size=top_k, **body)
            return [
                {"chunk_id": hit["_id"], "score": hit["_score"], "source": hit["_source"]}
                for hit in result.get("hits", {}).get("hits", [])
            ]
        except NotFoundError:
            return []
        except ESConnectionError as e:
            logger.error("ES 搜索异常（基础设施问题）", index=index_name, error=str(e))
            raise
        except Exception as e:
            logger.warning("%s失败", log_label, index=index_name, error=str(e))
            return []

    async def text_search(
        self, space_id: int, query: str, top_k: int = 5,
        kb_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """全文搜索（match 查询 content 字段，保留字符已转义）。

        Args:
            space_id: 空间 ID。
            query: 查询文本。
            top_k: 返回条数上限（自动截断到 MAX_SEARCH_RESULTS）。
            kb_id: 知识库过滤；None 表示不过滤。

        Returns:
            结果列表，每项含 chunk_id、score、source；失败返回空表。
        """
        top_k = min(top_k, MAX_SEARCH_RESULTS)
        index_name = self.generate_index_name(space_id)
        filters = self._build_kb_filter(kb_id)
        safe_query = self._escape_query(query)

        search_query = {"match": {self._schema.field_names.content: safe_query}}
        body = {"query": {"bool": {"must": [search_query], "filter": filters}}} if filters else {"query": search_query}
        return await self._execute_search(index_name, body, "全文搜索", top_k)

    async def hybrid_search(
        self,
        space_id: int,
        query: str,
        query_vector: list[float],
        top_k: int = 5,
        vector_weight: float = 0.7,
        text_weight: float = 0.3,
        rrf_k: int = 60,
        kb_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """混合搜索（向量 + 全文），使用加权 RRF 融合。

        Args:
            space_id: 空间 ID。
            query: 查询文本。
            query_vector: 查询向量。
            top_k: 融合后返回条数上限。
            vector_weight: 向量路权重。
            text_weight: 全文路权重。
            rrf_k: RRF 平滑常数（默认 60）。
            kb_id: 知识库过滤；None 表示不过滤。

        Returns:
            融合排序后的结果列表，每项含 chunk_id、score、source、hit_sources。
        """
        top_k = min(top_k, MAX_SEARCH_RESULTS)

        vector_results, text_results = await asyncio.gather(
            self.vector_search(space_id, query_vector, top_k * 2, kb_id=kb_id),
            self.text_search(space_id, query, top_k * 2, kb_id=kb_id),
        )

        return self.rrf_fuse(
            [vector_results, text_results],
            weights=[vector_weight, text_weight],
            k=rrf_k,
            top_k=top_k,
        )

    # ========== RRF 融合算法 ==========

    def rrf_fuse(
        self,
        result_sets: list[list[dict[str, Any]]],
        weights: list[float] | None = None,
        k: int = 60,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """加权 RRF 融合去重（score = sum(weight / (k + rank))）。

        Args:
            result_sets: 多路结果列表，每路为含 chunk_id/source 的 dict 列表。
            weights: 与各路一一对应的权重；None 或缺位按 1.0。
            k: RRF 平滑常数（排名越靠前贡献越大）。
            top_k: 融合后保留条数。

        Returns:
            按融合分降序的结果列表，每项含 chunk_id、score、source、hit_sources。
        """
        chunk_scores: dict[str, float] = {}
        chunk_data: dict[str, dict] = {}
        chunk_hit_sources: dict[str, list[str]] = {}

        for set_idx, results in enumerate(result_sets):
            if not results:
                continue
            source_name = f"search_{set_idx}"
            w = weights[set_idx] if weights and set_idx < len(weights) else 1.0
            for rank, item in enumerate(results, start=1):
                chunk_id = item.get("chunk_id")
                if not chunk_id:
                    continue

                if chunk_id not in chunk_scores:
                    chunk_scores[chunk_id] = 0.0
                    chunk_data[chunk_id] = item.get("source", item)
                    chunk_hit_sources[chunk_id] = []

                chunk_scores[chunk_id] += w / (k + rank)
                if source_name not in chunk_hit_sources[chunk_id]:
                    chunk_hit_sources[chunk_id].append(source_name)

        sorted_results = sorted(chunk_scores.items(), key=lambda x: x[1], reverse=True)[
            :top_k
        ]

        return [
            {
                "chunk_id": chunk_id,
                "score": round(score, 4),
                "source": chunk_data[chunk_id],
                "hit_sources": chunk_hit_sources[chunk_id],
            }
            for chunk_id, score in sorted_results
        ]

    # ========== 多模式检索方法 ==========

    async def content_bm25_search(
        self, space_id: int, query: str, top_k: int = 10,
        kb_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """内容 BM25 检索（text_search 的语义别名）。

        Args:
            space_id: 空间 ID。
            query: 查询文本。
            top_k: 返回条数上限。
            kb_id: 知识库过滤；None 表示不过滤。

        Returns:
            结果列表，每项含 chunk_id、score、source。
        """
        return await self.text_search(space_id, query, top_k, kb_id=kb_id)

    async def content_vector_search(
        self, space_id: int, query_vector: list[float], top_k: int = 10,
        kb_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """内容向量检索（vector_search 的语义别名）。

        Args:
            space_id: 空间 ID。
            query_vector: 查询向量。
            top_k: 返回条数上限。
            kb_id: 知识库过滤；None 表示不过滤。

        Returns:
            结果列表，每项含 chunk_id、score、source。
        """
        return await self.vector_search(space_id, query_vector, top_k, kb_id=kb_id)

    async def content_hybrid_search(
        self, space_id: int, query: str, query_vector: list[float],
        top_k: int = 10, vector_weight: float = 0.7, bm25_weight: float = 0.3,
        rrf_k: int = 60, kb_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """内容混合检索（BM25 + 向量，RRF 融合）。

        Args:
            space_id: 空间 ID。
            query: 查询文本。
            query_vector: 查询向量。
            top_k: 融合后返回条数上限。
            vector_weight: 向量路权重。
            bm25_weight: BM25 路权重。
            rrf_k: RRF 平滑常数。
            kb_id: 知识库过滤；None 表示不过滤。

        Returns:
            融合排序后的结果列表，每项含 chunk_id、score、source、hit_sources。
        """
        return await self.hybrid_search(
            space_id, query, query_vector, top_k, vector_weight, bm25_weight, rrf_k, kb_id=kb_id
        )

    async def question_bm25_search(
        self, space_id: int, query: str, top_k: int = 10,
        kb_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """问题 BM25 检索（match 查询 questions 字段）。

        Args:
            space_id: 空间 ID。
            query: 查询文本。
            top_k: 返回条数上限。
            kb_id: 知识库过滤；None 表示不过滤。

        Returns:
            结果列表，每项含 chunk_id、score、source。
        """
        top_k = min(top_k, MAX_SEARCH_RESULTS)
        index_name = self.generate_index_name(space_id)
        safe_query = self._escape_query(query)
        filters = self._build_kb_filter(kb_id)

        match_query = {"match": {self._schema.field_names.questions: safe_query}}
        body = {"query": {"bool": {"must": [match_query], "filter": filters}}} if filters else {"query": match_query}
        return await self._execute_search(index_name, body, "问题 BM25 检索", top_k)

    async def question_vector_search(
        self, space_id: int, query_vector: list[float], top_k: int = 10,
        kb_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """问题向量检索（nested 路径下 vector 子字段的 knn 查询）。

        Args:
            space_id: 空间 ID。
            query_vector: 查询向量。
            top_k: 返回条数上限。
            kb_id: 知识库过滤；None 表示不过滤。

        Returns:
            结果列表，每项含 chunk_id、score、source。
        """
        top_k = min(top_k, MAX_SEARCH_RESULTS)
        index_name = self.generate_index_name(space_id)
        filters = self._build_kb_filter(kb_id)
        fn = self._schema.field_names
        nested_path = fn.question_embeddings
        nested_field = f"{fn.question_embeddings}.{fn.question_embeddings_vector}"

        nested_query = {
            "nested": {
                "path": nested_path,
                "query": {
                    "knn": {
                        "field": nested_field,
                        "query_vector": query_vector,
                        "k": top_k,
                        "num_candidates": top_k * 3,
                    }
                },
                "score_mode": "max",
            }
        }
        body = {"query": {"bool": {"must": [nested_query], "filter": filters}}} if filters else {"query": nested_query}
        return await self._execute_search(index_name, body, "问题向量检索", top_k)

    async def question_hybrid_search(
        self, space_id: int, query: str, query_vector: list[float],
        top_k: int = 10, vector_weight: float = 0.7, bm25_weight: float = 0.3,
        rrf_k: int = 60, kb_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """问题混合检索（BM25 + 向量，RRF 融合）。

        Args:
            space_id: 空间 ID。
            query: 查询文本。
            query_vector: 查询向量。
            top_k: 融合后返回条数上限。
            vector_weight: 向量路权重。
            bm25_weight: BM25 路权重。
            rrf_k: RRF 平滑常数。
            kb_id: 知识库过滤；None 表示不过滤。

        Returns:
            融合排序后的结果列表，每项含 chunk_id、score、source、hit_sources。
        """
        top_k = min(top_k, MAX_SEARCH_RESULTS)

        vector_results, text_results = await asyncio.gather(
            self.question_vector_search(space_id, query_vector, top_k * 2, kb_id=kb_id),
            self.question_bm25_search(space_id, query, top_k * 2, kb_id=kb_id),
        )

        return self.rrf_fuse(
            [vector_results, text_results],
            weights=[vector_weight, bm25_weight],
            k=rrf_k,
            top_k=top_k,
        )

    async def all_bm25_search(
        self, space_id: int, query: str, top_k: int = 10,
        content_weight: float = 0.6, question_weight: float = 0.4,
        kb_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """全字段 BM25 检索（内容 + 问题，should 加权求和）。

        Args:
            space_id: 空间 ID。
            query: 查询文本。
            top_k: 返回条数上限。
            content_weight: content 字段 boost 权重。
            question_weight: questions 字段 boost 权重。
            kb_id: 知识库过滤；None 表示不过滤。

        Returns:
            结果列表，每项含 chunk_id、score、source；失败返回空表。
        """
        top_k = min(top_k, MAX_SEARCH_RESULTS)
        index_name = self.generate_index_name(space_id)
        safe_query = self._escape_query(query)
        filters = self._build_kb_filter(kb_id)

        try:
            fn = self._schema.field_names
            should_query = {
                "bool": {
                    "should": [
                        {"match": {fn.content: {"query": safe_query, "boost": content_weight}}},
                        {"match": {fn.questions: {"query": safe_query, "boost": question_weight}}},
                    ]
                }
            }
            if filters:
                body = {"query": {"bool": {"must": [should_query], "filter": filters}}}
            else:
                body = {"query": should_query}

            result = await self.es_client.search(index=index_name, size=top_k, **body)
            return [
                {
                    "chunk_id": hit["_id"],
                    "score": hit["_score"],
                    "source": hit["_source"],
                }
                for hit in result.get("hits", {}).get("hits", [])
            ]
        except Exception as e:
            logger.warning("全字段 BM25 检索失败", index=index_name, error=str(e))
            return []

    async def all_vector_search(
        self, space_id: int, query_vector: list[float], top_k: int = 10,
        content_weight: float = 0.6, question_weight: float = 0.4,
        kb_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """全字段向量检索（内容向量 + 问题向量，RRF 融合）。

        Args:
            space_id: 空间 ID。
            query_vector: 查询向量。
            top_k: 融合后返回条数上限。
            content_weight: 内容向量路权重。
            question_weight: 问题向量路权重。
            kb_id: 知识库过滤；None 表示不过滤。

        Returns:
            融合排序后的结果列表，每项含 chunk_id、score、source、hit_sources。
        """
        top_k = min(top_k, MAX_SEARCH_RESULTS)

        content_results, question_results = await asyncio.gather(
            self.content_vector_search(space_id, query_vector, top_k * 2, kb_id=kb_id),
            self.question_vector_search(space_id, query_vector, top_k * 2, kb_id=kb_id),
        )

        return self.rrf_fuse(
            [content_results, question_results],
            weights=[content_weight, question_weight],
            k=60,
            top_k=top_k,
        )

    async def all_hybrid_search(
        self, space_id: int, query: str, query_vector: list[float],
        top_k: int = 10, vector_weight: float = 0.7, bm25_weight: float = 0.3,
        content_weight: float = 0.6, question_weight: float = 0.4,
        rrf_k: int = 60, kb_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """全字段全算法融合检索（BM25/向量 x 内容/问题 四路 RRF）。

        Args:
            space_id: 空间 ID。
            query: 查询文本。
            query_vector: 查询向量。
            top_k: 融合后返回条数上限。
            vector_weight: 向量算法权重。
            bm25_weight: BM25 算法权重。
            content_weight: 内容侧权重。
            question_weight: 问题侧权重。
            rrf_k: RRF 平滑常数。
            kb_id: 知识库过滤；None 表示不过滤。

        Returns:
            融合排序后的结果列表（单路失败自动剔除该路，不整体失败）。
        """
        top_k = min(top_k, MAX_SEARCH_RESULTS)

        results = await asyncio.gather(
            self.content_bm25_search(space_id, query, top_k * 2, kb_id=kb_id),
            self.content_vector_search(space_id, query_vector, top_k * 2, kb_id=kb_id),
            self.question_bm25_search(space_id, query, top_k * 2, kb_id=kb_id),
            self.question_vector_search(space_id, query_vector, top_k * 2, kb_id=kb_id),
            return_exceptions=True,
        )

        valid_results = []
        valid_weights = []
        raw_weights = [
            bm25_weight * content_weight,
            vector_weight * content_weight,
            bm25_weight * question_weight,
            vector_weight * question_weight,
        ]
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.warning(f"检索 {i} 失败", error=str(r))
            elif r:
                valid_results.append(r)
                valid_weights.append(raw_weights[i])

        return self.rrf_fuse(valid_results, weights=valid_weights, k=rrf_k, top_k=top_k)

    # ========== 统一检索入口 ==========

    async def search_by_mode(
        self,
        space_id: int,
        mode: str,
        query: str,
        query_vector: list[float] | None = None,
        top_k: int = 10,
        vector_weight: float = 0.7,
        bm25_weight: float = 0.3,
        content_weight: float = 0.6,
        question_weight: float = 0.4,
        rrf_k: int = 60,
        kb_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """根据模式路由到对应的检索方法（统一入口）。

        Args:
            space_id: 空间 ID。
            mode: 检索模式（content_bm25/content_vector/content_hybrid/question_bm25/
                question_vector/question_hybrid/all_bm25/all_vector/all_hybrid）；
                未知模式回退 content_hybrid。
            query: 查询文本。
            query_vector: 查询向量；向量类模式缺省时降级为对应 BM25 或返回空表。
            top_k: 返回条数上限。
            vector_weight: 向量算法权重。
            bm25_weight: BM25 算法权重。
            content_weight: 内容侧权重。
            question_weight: 问题侧权重。
            rrf_k: RRF 平滑常数。
            kb_id: 知识库过滤；None 表示不过滤。

        Returns:
            结果列表，形状同具体模式方法。

        Raises:
            elasticsearch.ConnectionError: ES 连接类基础设施异常原样抛出。
        """
        mode_handlers = {
            "content_bm25": lambda: self.content_bm25_search(space_id, query, top_k, kb_id=kb_id),
            "content_vector": lambda: (
                self.content_vector_search(space_id, query_vector, top_k, kb_id=kb_id)
                if query_vector else []
            ),
            "content_hybrid": lambda: (
                self.content_hybrid_search(
                    space_id, query, query_vector, top_k, vector_weight, bm25_weight, rrf_k, kb_id=kb_id
                )
                if query_vector else self.content_bm25_search(space_id, query, top_k, kb_id=kb_id)
            ),
            "question_bm25": lambda: self.question_bm25_search(space_id, query, top_k, kb_id=kb_id),
            "question_vector": lambda: (
                self.question_vector_search(space_id, query_vector, top_k, kb_id=kb_id)
                if query_vector else []
            ),
            "question_hybrid": lambda: (
                self.question_hybrid_search(
                    space_id, query, query_vector, top_k, vector_weight, bm25_weight, rrf_k, kb_id=kb_id
                )
                if query_vector else self.question_bm25_search(space_id, query, top_k, kb_id=kb_id)
            ),
            "all_bm25": lambda: self.all_bm25_search(
                space_id, query, top_k, content_weight, question_weight, kb_id=kb_id
            ),
            "all_vector": lambda: (
                self.all_vector_search(
                    space_id, query_vector, top_k, content_weight, question_weight, kb_id=kb_id
                )
                if query_vector else []
            ),
            "all_hybrid": lambda: (
                self.all_hybrid_search(
                    space_id, query, query_vector, top_k,
                    vector_weight, bm25_weight, content_weight, question_weight,
                    rrf_k, kb_id=kb_id,
                )
                if query_vector else self.all_bm25_search(
                    space_id, query, top_k, content_weight, question_weight, kb_id=kb_id
                )
            ),
        }

        handler = mode_handlers.get(mode)
        if not handler:
            logger.warning("未知的检索模式，使用默认 content_hybrid", mode=mode)
            handler = mode_handlers.get("content_hybrid")

        try:
            return await handler()
        except NotFoundError:
            return []
        except ESConnectionError as e:
            logger.error("ES 搜索异常（基础设施问题）", mode=mode, error=str(e))
            raise
        except Exception as e:
            logger.warning("检索失败", mode=mode, error=str(e))
            return []
