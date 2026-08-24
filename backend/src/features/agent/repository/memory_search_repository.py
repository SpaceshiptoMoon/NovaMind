"""
Agent 长期记忆 ES 向量检索仓储

每个 Agent 独立索引 `agent_memory_{agent_id}`，支持：
- Hybrid 搜索（向量 cosine + BM25）
- 纯 BM25 fallback
- 按文档 ID 删除

MySQL 是 source of truth，ES 是检索加速层。ES 不可用时降级到 MySQL LIKE。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from elasticsearch import AsyncElasticsearch

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class MemorySearchRepository:
    """Agent 长期记忆 ES 向量检索仓储"""

    def __init__(
        self,
        es_client: AsyncElasticsearch,
        embedding_dim: int = 1536,
    ):
        self._es = es_client
        # 仅作 fallback：真实维度优先取自向量长度（index_memory/search 收到的 embedding），
        # 避免硬编码维度与实际 embedding 模型不一致（见 ES KNN 维度不匹配降级问题）
        self._embedding_dim = embedding_dim
        # 各索引实际 content_vector 维度缓存（避免每次搜索都查 mapping）
        self._index_dims: Dict[str, int] = {}

    def _index_name(self, agent_id: int) -> str:
        return f"agent_memory_{agent_id}"

    async def _get_index_dims(self, index_name: str) -> Optional[int]:
        """读取并缓存索引 content_vector 的实际维度"""
        if index_name in self._index_dims:
            return self._index_dims[index_name]
        try:
            mapping = await self._es.indices.get_mapping(index=index_name)
            props = mapping[index_name]["mappings"]["properties"]
            dims = props.get("content_vector", {}).get("dims")
            if dims is not None:
                self._index_dims[index_name] = int(dims)
                return int(dims)
        except Exception as e:
            logger.warning("读取记忆索引维度失败", index_name=index_name, error=str(e))
        return None

    # ==================== 索引管理 ====================

    async def ensure_index(
        self,
        agent_id: int,
        embedding_dim: Optional[int] = None,
    ) -> bool:
        """确保索引存在且维度匹配。

        维度优先取 embedding_dim（向量实际长度）；缺失时回退构造默认（仅用于无向量上下文的预创建）。
        若已有索引维度与 embedding_dim 不一致（embedding 模型变更导致陈旧索引），
        删除旧索引并按新维度重建——ES 仅是检索加速层，MySQL 是 source of truth，重建安全。

        Returns:
            True 表示因维度不匹配重建了索引（调用方应从 MySQL 重索引全部记忆）。
        """
        index_name = self._index_name(agent_id)
        dim = embedding_dim or self._embedding_dim

        if await self._es.indices.exists(index=index_name):
            if embedding_dim is None:
                # 无目标维度（如预创建）：不重建，保持现状，待 index_memory 携带向量时自愈
                return False
            existing = await self._get_index_dims(index_name)
            if existing is not None and existing != dim:
                logger.warning(
                    "记忆索引维度不匹配，重建索引",
                    index_name=index_name, old_dim=existing, new_dim=dim,
                )
                try:
                    await self._es.indices.delete(index=index_name)
                except Exception as e:
                    logger.warning("删除陈旧记忆索引失败", index_name=index_name, error=str(e))
                    return False
                self._index_dims.pop(index_name, None)
                await self._create_index(index_name, dim)
                return True  # 因维度不匹配重建，调用方应重索引全部记忆
            return False

        await self._create_index(index_name, dim)
        return False

    async def _create_index(self, index_name: str, dim: int) -> None:
        """按指定维度创建索引（幂等，已存在则忽略）"""
        mapping = {
            "mappings": {
                "properties": {
                    "memory_id": {"type": "long"},
                    "user_id": {"type": "long"},
                    "category": {"type": "keyword"},
                    "content": {"type": "text", "analyzer": "standard"},
                    "content_vector": {
                        "type": "dense_vector",
                        "dims": dim,
                        "index": True,
                        "similarity": "cosine",
                    },
                    "source_conversation_id": {"type": "long"},
                    "source_type": {"type": "keyword"},
                    "created_at": {"type": "date"},
                    "access_count": {"type": "integer"},
                },
            },
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
        }
        try:
            await self._es.indices.create(index=index_name, body=mapping)
            self._index_dims[index_name] = dim
            logger.info("Agent 记忆索引已创建", index_name=index_name, dims=dim)
        except Exception as e:
            if "resource_already_exists_exception" not in str(e):
                raise

    # ==================== 文档操作 ====================

    async def index_memory(
        self,
        agent_id: int,
        memory_id: int,
        user_id: int,
        category: str,
        content: str,
        embedding: List[float],
        source_type: str = "consolidate",
        source_conversation_id: Optional[int] = None,
        created_at: Optional[datetime] = None,
    ) -> bool:
        """索引单条记忆到 ES。

        用 len(embedding) 作为真实维度触发 ensure_index 自愈：若已有索引维度与当前
        embedding 模型不一致，自动重建索引。

        Returns:
            True 表示索引因维度不匹配被重建（调用方应从 MySQL 重索引全部记忆）。
        """
        try:
            recreated = await self.ensure_index(agent_id, embedding_dim=len(embedding))
            doc: Dict[str, Any] = {
                "memory_id": memory_id,
                "user_id": user_id,
                "category": category,
                "content": content,
                "content_vector": embedding,
                "source_type": source_type,
                "access_count": 0,
            }
            if source_conversation_id is not None:
                doc["source_conversation_id"] = source_conversation_id
            if created_at is not None:
                doc["created_at"] = created_at.isoformat()

            await self._es.index(
                index=self._index_name(agent_id),
                id=str(memory_id),
                document=doc,
            )
            if recreated:
                logger.info("记忆索引已重建，需重索引全部记忆", agent_id=agent_id)
            return recreated
        except Exception as e:
            logger.warning("ES 记忆索引失败", memory_id=memory_id, error=str(e))
            return False

    async def search(
        self,
        agent_id: int,
        query_vector: List[float],
        query_text: str,
        top_k: int = 5,
        user_id: Optional[int] = None,
        categories: Optional[List[str]] = None,
        vector_weight: float = 0.7,
        text_weight: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid 搜索：原生 KNN 向量检索 + BM25 文本检索，RRF 融合

        使用 ES 原生 knn 参数（而非 script_score），性能更优。
        结果按 access_count 做频次加权（高频访问的记忆略微提权）。

        Args:
            agent_id: Agent ID
            query_vector: 查询向量
            query_text: 查询文本
            top_k: 返回结果数
            user_id: 过滤用户 ID
            categories: 过滤记忆类别
            vector_weight: 向量搜索权重（用于 RRF）
            text_weight: 文本搜索权重（用于 RRF）
        """
        index_name = self._index_name(agent_id)

        if not await self._es.indices.exists(index=index_name):
            return []

        filter_clauses: List[Dict] = []
        if user_id is not None:
            filter_clauses.append({"term": {"user_id": user_id}})
        if categories:
            filter_clauses.append({"terms": {"category": categories}})

        # 维度校验：查询向量维度须与索引 content_vector 维度一致，否则 KNN 会 400。
        # 模型变更后的过渡期（索引尚未自愈重建）静默降级 BM25，不刷 warning 噪音。
        index_dims = await self._get_index_dims(index_name)
        knn_available = (
            index_dims is None  # 读不到维度时冒险一试，失败再降级
            or index_dims == len(query_vector)
        )

        if knn_available:
            # 构建 KNN 查询
            knn_query: Dict[str, Any] = {
                "field": "content_vector",
                "query_vector": query_vector,
                "k": top_k,
                "num_candidates": top_k * 3,
            }
            if filter_clauses:
                knn_query["filter"] = {"bool": {"filter": filter_clauses}}

            # 构建 BM25 文本查询
            text_query: Dict[str, Any] = {
                "bool": {
                    "filter": filter_clauses if filter_clauses else [],
                    "should": [
                        {"match": {"content": {"query": query_text, "boost": text_weight}}}
                    ],
                }
            }

            body: Dict[str, Any] = {
                "size": top_k,
                "knn": knn_query,
                "query": text_query,
            }

            try:
                result = await self._es.search(index=index_name, body=body)
                hits = result["hits"]["hits"]
                return [
                    {
                        "memory_id": hit["_source"]["memory_id"],
                        "category": hit["_source"]["category"],
                        "content": hit["_source"]["content"],
                        "access_count": hit["_source"].get("access_count", 0),
                        "score": hit["_score"],
                    }
                    for hit in hits
                ]
            except Exception as e:
                logger.warning("ES KNN hybrid 搜索失败，降级 BM25", agent_id=agent_id, error=str(e))
                # 降级：纯 BM25
                return await self._fallback_bm25_search(index_name, query_text, top_k, filter_clauses)

        # 维度不匹配：直接 BM25（不进入 KNN 避免 400）
        logger.debug(
            "记忆查询向量维度与索引不一致，跳过 KNN 用 BM25",
            agent_id=agent_id, query_dim=len(query_vector), index_dim=index_dims,
        )
        return await self._fallback_bm25_search(index_name, query_text, top_k, filter_clauses)

    async def _fallback_bm25_search(
        self,
        index_name: str,
        query_text: str,
        top_k: int,
        filter_clauses: List[Dict],
    ) -> List[Dict[str, Any]]:
        """KNN 失败时降级到纯 BM25 搜索"""
        body: Dict[str, Any] = {
            "size": top_k,
            "query": {
                "bool": {
                    "filter": filter_clauses if filter_clauses else [],
                    "must": [{"match": {"content": query_text}}],
                }
            },
        }
        try:
            result = await self._es.search(index=index_name, body=body)
            return [
                {
                    "memory_id": hit["_source"]["memory_id"],
                    "category": hit["_source"]["category"],
                    "content": hit["_source"]["content"],
                    "access_count": hit["_source"].get("access_count", 0),
                    "score": hit["_score"],
                }
                for hit in result["hits"]["hits"]
            ]
        except Exception as e:
            logger.warning("ES BM25 降级搜索也失败", index_name=index_name, error=str(e))
            return []

    async def delete_memory(self, agent_id: int, memory_id: int) -> bool:
        """删除 ES 中的记忆文档"""
        try:
            index_name = self._index_name(agent_id)
            if await self._es.indices.exists(index=index_name):
                await self._es.delete(
                    index=index_name, id=str(memory_id), ignore=[404]
                )
                return True
        except Exception as e:
            logger.warning("ES 记忆删除失败", memory_id=memory_id, error=str(e))
        return False
