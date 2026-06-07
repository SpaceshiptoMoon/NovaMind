"""
Elasticsearch 客户端封装

提供统一的向量存储和全文检索功能
每个知识空间使用独立的索引
"""

import asyncio
import re
from typing import Optional, List, Dict, Any
from datetime import datetime
from elasticsearch import AsyncElasticsearch

from src.core.middleware.structured_logging import get_logger

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
        hosts: List[str],
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_ssl: bool = False,
        verify_certs: bool = True,
        ca_certs: Optional[str] = None,
        default_embedding_dim: int = 1024,
        default_analyzer: str = "standard",
    ):
        self.verify_certs = verify_certs
        self.ca_certs = ca_certs
        self.default_embedding_dim = default_embedding_dim
        self.default_analyzer = default_analyzer

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
        try:
            return await self.es_client.ping()
        except Exception as e:
            logger.error("Elasticsearch 连接检查失败", error=str(e))
            return False

    async def close(self) -> None:
        await self.es_client.close()
        logger.info("Elasticsearch 客户端已关闭")

    # ========== 索引管理 ==========

    def generate_index_name(self, space_id: int) -> str:
        """生成空间索引名称"""
        return f"space_{space_id}"

    async def index_exists(self, space_id: int) -> bool:
        """检查索引是否存在"""
        index_name = self.generate_index_name(space_id)
        try:
            return bool(await self.es_client.indices.exists(index=index_name))
        except Exception as e:
            logger.error("检查索引失败", index=index_name, error=str(e))
            return False

    async def create_index(
        self,
        space_id: int,
        embedding_dim: Optional[int] = None,
        analyzer: Optional[str] = None,
        multimodal_dim: Optional[int] = None,
    ) -> bool:
        """创建空间索引（幂等：索引已存在时直接返回成功）"""
        index_name = self.generate_index_name(space_id)
        dim = embedding_dim or self.default_embedding_dim
        _analyzer = analyzer or self.default_analyzer

        is_ik = _analyzer.startswith("ik_")
        search_analyzer = "ik_smart" if is_ik else "standard"

        properties = {
            "space_id": {"type": "long"},
            "kb_id": {"type": "long"},
            "document_id": {"type": "long"},
            "chunk_id": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "content": {
                "type": "text",
                "analyzer": _analyzer,
                "search_analyzer": search_analyzer,
            },
            "embedding": {
                "type": "dense_vector",
                "dims": dim,
                "index": True,
                "similarity": "cosine",
            },
            "questions": {
                "type": "text",
                "analyzer": _analyzer,
                "search_analyzer": search_analyzer,
            },
            "question_embeddings": {
                "type": "nested",
                "properties": {
                    "vector": {
                        "type": "dense_vector",
                        "dims": dim,
                        "index": True,
                        "similarity": "cosine",
                    }
                },
            },
            "chunk_type": {"type": "keyword"},
            "image_url": {"type": "keyword"},
            "metadata": {
                "properties": {
                    "page_number": {"type": "integer"},
                    "section_title": {"type": "text"},
                    "char_start": {"type": "integer"},
                    "char_end": {"type": "integer"},
                    "content_hash": {"type": "keyword"},
                }
            },
            "file_info": {
                "properties": {
                    "filename": {"type": "keyword"},
                    "file_type": {"type": "keyword"},
                }
            },
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }

        if multimodal_dim:
            properties["image_embedding"] = {
                "type": "dense_vector",
                "dims": multimodal_dim,
                "index": True,
                "similarity": "cosine",
            }

        mappings = {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
            "mappings": {
                "properties": properties,
            },
        }

        try:
            await self.es_client.indices.create(
                index=index_name,
                settings=mappings["settings"],
                mappings=mappings["mappings"],
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
        self, space_id: int, embedding_dim: Optional[int] = None, multimodal_dim: Optional[int] = None
    ) -> str:
        """确保索引存在"""
        index_name = self.generate_index_name(space_id)
        if not await self.index_exists(space_id):
            await self.create_index(space_id, embedding_dim, multimodal_dim=multimodal_dim)
        return index_name

    async def delete_index(self, space_id: int) -> bool:
        """删除空间索引"""
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
        """删除空间索引中指定知识库的所有文档"""
        index_name = self.generate_index_name(space_id)
        try:
            result = await self.es_client.delete_by_query(
                index=index_name,
                body={"query": {"term": {"kb_id": kb_id}}},
            )
            deleted = result.get("deleted", 0)
            logger.info("删除知识库文档成功", index=index_name, kb_id=kb_id, deleted=deleted)
            return deleted
        except Exception as e:
            logger.error("删除知识库文档失败", index=index_name, kb_id=kb_id, error=str(e))
            return 0

    # ========== 文档操作 ==========

    async def index_chunk(self, space_id: int, chunk_data: Dict[str, Any]) -> bool:
        """索引单个分块"""
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
        chunks: List[Dict[str, Any]],
        embedding_dim: Optional[int] = None,
        multimodal_dim: Optional[int] = None,
    ) -> int:
        """批量索引分块"""
        if not chunks:
            return 0

        index_name = await self.ensure_index_exists(
            space_id, embedding_dim=embedding_dim, multimodal_dim=multimodal_dim
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

    async def image_vector_search(
        self,
        space_id: int,
        query_vector: List[float],
        top_k: int = 10,
        kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """在 image_embedding 字段上做 KNN 搜索（以图搜图 / 以文搜图）"""
        return await self.vector_search(
            space_id=space_id,
            query_vector=query_vector,
            top_k=top_k,
            kb_id=kb_id,
            field="image_embedding",
            chunk_type_filter="image",
        )

    async def image_hybrid_vector_search(
        self,
        space_id: int,
        query_vector: List[float],
        top_k: int = 10,
        kb_id: Optional[int] = None,
        text_vector_weight: float = 0.5,
        image_vector_weight: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """双向量搜索：同时搜索 embedding（描述文本向量）和 image_embedding（图片向量），RRF 融合

        适用于 text_to_image 模式，当图片 chunk 有 VLM 描述时，同时匹配描述文本和图片向量。

        Args:
            space_id: 空间 ID
            query_vector: 查询向量
            top_k: 返回数量
            kb_id: 知识库 ID（可选过滤）
            text_vector_weight: 描述文本向量权重（默认 0.5）
            image_vector_weight: 图片向量权重（默认 0.5）

        Returns:
            RRF 融合后的搜索结果
        """
        fetch_size = top_k * 2  # 多取一些用于融合后截断

        # 并行搜索两个向量字段
        text_results, image_results = await asyncio.gather(
            self.vector_search(
                space_id=space_id,
                query_vector=query_vector,
                top_k=fetch_size,
                kb_id=kb_id,
                field="embedding",
                chunk_type_filter="image",
            ),
            self.image_vector_search(
                space_id=space_id,
                query_vector=query_vector,
                top_k=fetch_size,
                kb_id=kb_id,
            ),
        )

        return self.rrf_fuse(
            [text_results, image_results],
            weights=[text_vector_weight, image_vector_weight],
            k=60,
            top_k=top_k,
        )

    async def get_chunk(self, space_id: int, chunk_id: str) -> Optional[Dict[str, Any]]:
        """获取分块"""
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
        """删除分块"""
        index_name = self.generate_index_name(space_id)
        try:
            await self.es_client.delete(index=index_name, id=chunk_id)
            return True
        except Exception as e:
            logger.error("删除分块失败", chunk_id=chunk_id, error=str(e))
            return False

    async def delete_document_chunks(self, space_id: int, document_id: int) -> int:
        """删除文档的所有分块"""
        index_name = self.generate_index_name(space_id)
        try:
            result = await self.es_client.delete_by_query(
                index=index_name, body={"query": {"term": {"document_id": document_id}}}
            )
            return result.get("deleted", 0)
        except Exception as e:
            logger.error("删除文档分块失败", document_id=document_id, error=str(e))
            return 0

    async def get_document_chunks(
        self, space_id: int, document_id: int, skip: int = 0, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取文档的所有分块"""
        index_name = self.generate_index_name(space_id)
        try:
            result = await self.es_client.search(
                index=index_name,
                query={"term": {"document_id": document_id}},
                from_=skip,
                size=limit,
                sort=[{"chunk_index": {"order": "asc"}}],
            )
            return [
                {"chunk_id": hit["_id"], "score": hit["_score"], **hit["_source"]}
                for hit in result.get("hits", {}).get("hits", [])
            ]
        except Exception as e:
            logger.error("获取文档分块失败", document_id=document_id, error=str(e))
            return []

    # ========== 搜索辅助 ==========

    def _build_kb_filter(self, kb_id: Optional[int] = None) -> List[Dict]:
        """构建知识库过滤条件"""
        if kb_id is not None:
            return [{"term": {"kb_id": kb_id}}]
        return []

    # ========== 搜索功能 ==========

    async def vector_search(
        self, space_id: int, query_vector: List[float], top_k: int = 5,
        kb_id: Optional[int] = None,
        field: str = "embedding",
        chunk_type_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """向量相似度搜索（统一入口，支持 embedding / image_embedding 字段）"""
        top_k = min(top_k, MAX_SEARCH_RESULTS)
        index_name = self.generate_index_name(space_id)
        filters = self._build_kb_filter(kb_id)
        if chunk_type_filter:
            filters.append({"term": {"chunk_type": chunk_type_filter}})

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
        except Exception as e:
            logger.warning("向量搜索失败", index=index_name, error=str(e))
            return []

    @staticmethod
    def _escape_query(query: str) -> str:
        if not query:
            return ""
        return ES_SPECIAL_CHARS.sub(r"\\\g<0>", query)

    async def text_search(
        self, space_id: int, query: str, top_k: int = 5,
        kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """全文搜索"""
        top_k = min(top_k, MAX_SEARCH_RESULTS)
        index_name = self.generate_index_name(space_id)
        filters = self._build_kb_filter(kb_id)
        safe_query = self._escape_query(query)

        try:
            search_query = {"match": {"content": safe_query}}
            if filters:
                body = {
                    "query": {
                        "bool": {
                            "must": [search_query],
                            "filter": filters,
                        }
                    }
                }
            else:
                body = {"query": search_query}

            result = await self.es_client.search(
                index=index_name,
                size=top_k,
                **body,
            )
            return [
                {
                    "chunk_id": hit["_id"],
                    "score": hit["_score"],
                    "source": hit["_source"],
                }
                for hit in result.get("hits", {}).get("hits", [])
            ]
        except Exception as e:
            logger.warning("全文搜索失败", index=index_name, error=str(e))
            return []

    async def hybrid_search(
        self,
        space_id: int,
        query: str,
        query_vector: List[float],
        top_k: int = 5,
        vector_weight: float = 0.7,
        text_weight: float = 0.3,
        rrf_k: int = 60,
        kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """混合搜索（向量 + 全文），使用加权 RRF 融合"""
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
        result_sets: List[List[Dict[str, Any]]],
        weights: Optional[List[float]] = None,
        k: int = 60,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """加权 RRF 融合去重"""
        chunk_scores: Dict[str, float] = {}
        chunk_data: Dict[str, Dict] = {}
        chunk_hit_sources: Dict[str, List[str]] = {}

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
        kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """内容 BM25 检索"""
        return await self.text_search(space_id, query, top_k, kb_id=kb_id)

    async def content_vector_search(
        self, space_id: int, query_vector: List[float], top_k: int = 10,
        kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """内容向量检索"""
        return await self.vector_search(space_id, query_vector, top_k, kb_id=kb_id)

    async def content_hybrid_search(
        self, space_id: int, query: str, query_vector: List[float],
        top_k: int = 10, vector_weight: float = 0.7, bm25_weight: float = 0.3,
        kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """内容混合检索（BM25 + 向量）"""
        return await self.hybrid_search(
            space_id, query, query_vector, top_k, vector_weight, bm25_weight, kb_id=kb_id
        )

    async def question_bm25_search(
        self, space_id: int, query: str, top_k: int = 10,
        kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """问题 BM25 检索"""
        top_k = min(top_k, MAX_SEARCH_RESULTS)
        index_name = self.generate_index_name(space_id)
        safe_query = self._escape_query(query)
        filters = self._build_kb_filter(kb_id)

        try:
            match_query = {"match": {"questions": safe_query}}
            if filters:
                body = {"query": {"bool": {"must": [match_query], "filter": filters}}}
            else:
                body = {"query": match_query}

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
            logger.warning("问题 BM25 检索失败", index=index_name, error=str(e))
            return []

    async def question_vector_search(
        self, space_id: int, query_vector: List[float], top_k: int = 10,
        kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """问题向量检索"""
        top_k = min(top_k, MAX_SEARCH_RESULTS)
        index_name = self.generate_index_name(space_id)
        filters = self._build_kb_filter(kb_id)

        try:
            nested_query = {
                "nested": {
                    "path": "question_embeddings",
                    "query": {
                        "knn": {
                            "field": "question_embeddings.vector",
                            "query_vector": query_vector,
                            "k": top_k,
                            "num_candidates": top_k * 3,
                        }
                    },
                    "score_mode": "max",
                }
            }
            if filters:
                body = {
                    "query": {
                        "bool": {
                            "must": [nested_query],
                            "filter": filters,
                        }
                    }
                }
            else:
                body = {"query": nested_query}

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
            logger.warning("问题向量检索失败", index=index_name, error=str(e))
            return []

    async def question_hybrid_search(
        self, space_id: int, query: str, query_vector: List[float],
        top_k: int = 10, vector_weight: float = 0.7, bm25_weight: float = 0.3,
        rrf_k: int = 60, kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """问题混合检索（BM25 + 向量）"""
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
        kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """全字段 BM25 检索（内容 + 问题）"""
        top_k = min(top_k, MAX_SEARCH_RESULTS)
        index_name = self.generate_index_name(space_id)
        safe_query = self._escape_query(query)
        filters = self._build_kb_filter(kb_id)

        try:
            should_query = {
                "bool": {
                    "should": [
                        {"match": {"content": {"query": safe_query, "boost": content_weight}}},
                        {"match": {"questions": {"query": safe_query, "boost": question_weight}}},
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
        self, space_id: int, query_vector: List[float], top_k: int = 10,
        content_weight: float = 0.6, question_weight: float = 0.4,
        kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """全字段向量检索（内容向量 + 问题向量）"""
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
        self, space_id: int, query: str, query_vector: List[float],
        top_k: int = 10, vector_weight: float = 0.7, bm25_weight: float = 0.3,
        content_weight: float = 0.6, question_weight: float = 0.4,
        rrf_k: int = 60, kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """全字段全算法融合检索"""
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
        query_vector: Optional[List[float]] = None,
        top_k: int = 10,
        vector_weight: float = 0.7,
        bm25_weight: float = 0.3,
        content_weight: float = 0.6,
        question_weight: float = 0.4,
        rrf_k: int = 60,
        kb_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """根据模式路由到对应的检索方法"""
        mode_handlers = {
            "content_bm25": lambda: self.content_bm25_search(space_id, query, top_k, kb_id=kb_id),
            "content_vector": lambda: (
                self.content_vector_search(space_id, query_vector, top_k, kb_id=kb_id)
                if query_vector else []
            ),
            "content_hybrid": lambda: (
                self.content_hybrid_search(
                    space_id, query, query_vector, top_k, vector_weight, bm25_weight, kb_id=kb_id
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
                    space_id, query, query_vector, top_k, vector_weight, bm25_weight, kb_id=kb_id
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
        except Exception as e:
            logger.warning("检索失败", mode=mode, error=str(e))
            return []
