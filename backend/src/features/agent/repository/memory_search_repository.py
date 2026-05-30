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

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class MemorySearchRepository:
    """Agent 长期记忆 ES 向量检索仓储"""

    def __init__(
        self,
        es_client: AsyncElasticsearch,
        embedding_dim: int = 1536,
    ):
        self._es = es_client
        self._embedding_dim = embedding_dim

    def _index_name(self, agent_id: int) -> str:
        return f"agent_memory_{agent_id}"

    # ==================== 索引管理 ====================

    async def ensure_index(self, agent_id: int) -> str:
        """确保索引存在，不存在则创建（幂等）"""
        index_name = self._index_name(agent_id)
        if await self._es.indices.exists(index=index_name):
            return index_name

        mapping = {
            "mappings": {
                "properties": {
                    "memory_id": {"type": "long"},
                    "user_id": {"type": "long"},
                    "category": {"type": "keyword"},
                    "content": {"type": "text", "analyzer": "standard"},
                    "content_vector": {
                        "type": "dense_vector",
                        "dims": self._embedding_dim,
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
            logger.info("Agent 记忆索引已创建", index_name=index_name)
        except Exception as e:
            if "resource_already_exists_exception" in str(e):
                return index_name
            raise

        return index_name

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
    ) -> None:
        """索引单条记忆到 ES"""
        try:
            await self.ensure_index(agent_id)
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
        except Exception as e:
            logger.warning("ES 记忆索引失败", memory_id=memory_id, error=str(e))

    async def search(
        self,
        agent_id: int,
        query_vector: List[float],
        query_text: str,
        top_k: int = 5,
        user_id: Optional[int] = None,
        categories: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Hybrid 搜索：向量 cosine + BM25"""
        index_name = self._index_name(agent_id)

        if not await self._es.indices.exists(index=index_name):
            return []

        filter_clauses: List[Dict] = []
        if user_id is not None:
            filter_clauses.append({"term": {"user_id": user_id}})
        if categories:
            filter_clauses.append({"terms": {"category": categories}})

        body: Dict[str, Any] = {
            "size": top_k,
            "query": {
                "bool": {
                    "filter": filter_clauses,
                    "should": [
                        {
                            "script_score": {
                                "query": {"match_all": {}},
                                "script": {
                                    "source": "cosineSimilarity(params.query_vector, 'content_vector') + 1.0",
                                    "params": {"query_vector": query_vector},
                                },
                            }
                        },
                        {"match": {"content": {"query": query_text, "boost": 0.3}}},
                    ],
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
                    "score": hit["_score"],
                }
                for hit in result["hits"]["hits"]
            ]
        except Exception as e:
            logger.warning("ES hybrid 搜索失败", agent_id=agent_id, error=str(e))
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
