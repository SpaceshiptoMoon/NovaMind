"""
向量化服务

处理文档分块的向量生成
支持 Embedding 缓存，避免重复 API 调用
向量存储在 Elasticsearch 中，由 DocumentService 调用

注意: 分块数据仅存储在 Elasticsearch 中，不在 MySQL 中存储

重要改造：
- 支持外部注入 embedding_client（用于知识库绑定特定模型）
- 缓存 key 包含模型名称，避免不同模型的向量混用
"""

from typing import List, Dict, Any
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.api.exceptions import EmbeddingError
from novamind.shared.ai_models.embedding import BaseEmbedding
from novamind.shared.cache.redis_client import get_redis_client
from novamind.core.middleware.structured_logging import get_logger


# 缓存 TTL 常量（单位：秒）
EMBEDDING_CACHE_TTL = 172800  # 48 小时


class EmbeddingService:
    """
    向量化服务

    处理文本到向量的转换
    支持 Embedding 缓存，避免重复 API 调用
    向量存储由 ElasticsearchClient 处理（在 DocumentService 中调用）

    注意: 分块数据仅存储在 Elasticsearch 中，不在 MySQL 中存储

    改造点：
    - 支持外部注入 embedding_client
    - 缓存 key 包含模型名称，格式: emb:{model_name}:text:{hash}
    """

    def __init__(
        self,
        session: AsyncSession,
        embedding_client: BaseEmbedding,
        model_name: str | None = None,
    ):
        """
        初始化 Embedding 服务

        Args:
            session: 数据库会话
            embedding_client: 外部注入的 Embedding 客户端（可选）
            model_name: 模型名称，用于缓存 key 隔离（可选，默认使用 "default"）
        """
        self.session = session
        # 必须由调用方注入 Embedding 客户端（通过 ModelConfigService 获取）
        if embedding_client is None:
            raise ValueError("EmbeddingClient 必须由调用方注入，通过 ModelConfigService 获取")
        self.embedding_client: BaseEmbedding = embedding_client
        self.model_name = model_name or "default"
        self.logger = get_logger(__name__)
        self._cache = None

        # 从客户端属性获取维度
        self._embedding_dim = None
        if hasattr(self.embedding_client, 'expected_dimension') and self.embedding_client.expected_dimension:
            self._embedding_dim = self.embedding_client.expected_dimension

    @property
    def embedding_dim(self) -> int:
        """获取向量维度"""
        return self._embedding_dim

    async def _get_cache(self):
        """获取 Redis 缓存客户端"""
        if self._cache is None:
            self._cache = await get_redis_client()
        return self._cache

    @staticmethod
    def _generate_text_hash(text: str) -> str:
        """生成文本内容的哈希值"""
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    def _get_embedding_cache_key(self, text_hash: str) -> str:
        """
        生成 embedding 缓存键

        格式: emb:{model_name}:text:{text_hash}
        不同模型的向量缓存隔离，避免切换模型后使用错误的向量
        """
        return f"emb:{self.model_name}:text:{text_hash}"

    async def get_embedding_with_cache(self, text: str) -> List[float]:
        """
        获取文本的 embedding（带缓存）

        优先从缓存获取，未命中则调用 API 并缓存结果

        Args:
            text: 文本内容

        Returns:
            embedding 向量

        Raises:
            EmbeddingError: 向量生成失败
        """
        text_hash = self._generate_text_hash(text)
        cache_key = self._get_embedding_cache_key(text_hash)

        try:
            # 1. 尝试从缓存获取
            cache = await self._get_cache()
            cached = await cache.get(cache_key)
            if cached is not None:
                self.logger.debug("Embedding 缓存命中", text_hash=text_hash)
                return cached

            self.logger.debug("Embedding 缓存未命中", text_hash=text_hash)

            # 2. 调用 API 生成
            embedding = await self.embedding_client.generate_embedding(text)

            # 3. 缓存结果
            await cache.set(cache_key, embedding, expire=EMBEDDING_CACHE_TTL)
            self.logger.debug("Embedding 已缓存", text_hash=text_hash, ttl=EMBEDDING_CACHE_TTL)

            return embedding

        except EmbeddingError:
            raise
        except Exception as e:
            self.logger.warning("Embedding 缓存操作失败，直接调用 API", error=str(e))
            # 缓存失败时直接调用 API
            try:
                return await self.embedding_client.generate_embedding(text)
            except EmbeddingError:
                raise
            except Exception as api_error:
                self.logger.error(
                    "Embedding API 调用失败",
                    text_hash=text_hash,
                    error=str(api_error),
                )
                raise EmbeddingError("Embedding API 调用失败，请稍后重试")

    async def get_embeddings_batch_with_cache(self, texts: List[str]) -> List[List[float]]:
        """
        批量获取 embedding（带缓存）

        检查每个文本的缓存状态，仅对未缓存的文本调用 API

        Args:
            texts: 文本列表

        Returns:
            embedding 向量列表

        Raises:
            EmbeddingError: 批量向量生成失败
        """
        if not texts:
            return []

        results = [None] * len(texts)
        uncached_indices = []
        uncached_texts = []

        try:
            cache = await self._get_cache()

            # 1. 构建所有缓存键并使用 mget 批量获取
            cache_keys = []
            for text in texts:
                text_hash = self._generate_text_hash(text)
                cache_key = self._get_embedding_cache_key(text_hash)
                cache_keys.append(cache_key)

            cached_values = await cache.mget(*cache_keys)

            for i, cached in enumerate(cached_values):
                if cached is not None:
                    results[i] = cached
                else:
                    uncached_indices.append(i)
                    uncached_texts.append(texts[i])

            # 2. 批量生成未缓存的 embedding
            if uncached_texts:
                self.logger.debug(
                    "批量 Embedding 缓存未命中",
                    total=len(texts),
                    uncached=len(uncached_texts),
                )

                try:
                    new_embeddings = await self.embedding_client.generate_embeddings_batch(uncached_texts)
                except Exception as api_error:
                    self.logger.error(
                        "批量 Embedding API 调用失败",
                        count=len(uncached_texts),
                        error=str(api_error),
                    )
                    raise EmbeddingError("批量 Embedding API 调用失败，请稍后重试")

                # 3. 缓存新生成的 embedding
                for idx, text, embedding in zip(uncached_indices, uncached_texts, new_embeddings):
                    results[idx] = embedding
                    text_hash = self._generate_text_hash(text)
                    cache_key = self._get_embedding_cache_key(text_hash)
                    await cache.set(cache_key, embedding, expire=EMBEDDING_CACHE_TTL)

                self.logger.debug(
                    "批量 Embedding 已缓存",
                    count=len(uncached_texts),
                    ttl=EMBEDDING_CACHE_TTL,
                )

            return results

        except EmbeddingError:
            raise
        except Exception as e:
            self.logger.warning("批量 Embedding 缓存操作失败，直接调用 API", error=str(e))
            # 缓存失败时直接调用 API
            try:
                return await self.embedding_client.generate_embeddings_batch(texts)
            except EmbeddingError:
                raise
            except Exception as api_error:
                self.logger.error(
                    "批量 Embedding API 调用失败（降级路径）",
                    count=len(texts),
                    error=str(api_error),
                )
                raise EmbeddingError("批量 Embedding API 调用失败，请稍后重试")

    async def generate_query_embedding(self, query: str) -> List[float]:
        """
        生成查询文本的向量（带缓存）

        Args:
            query: 查询文本

        Returns:
            查询向量

        Raises:
            EmbeddingError: 向量生成失败
        """
        return await self.get_embedding_with_cache(query)

    async def estimate_tokens(self, text: str) -> int:
        """
        估算文本的 token 数量

        简单估算：中文约 1.5 字符/token，英文约 4 字符/token

        Args:
            text: 文本内容

        Returns:
            估算的 token 数量
        """
        if not text:
            return 0

        # 简单估算
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars

        return int(chinese_chars / 1.5 + other_chars / 4)

    async def get_embedding_stats(self, texts: List[str]) -> Dict[str, Any]:
        """
        获取 embedding 统计信息

        Args:
            texts: 文本列表

        Returns:
            统计信息
        """
        total_tokens = sum([await self.estimate_tokens(t) for t in texts])

        return {
            "text_count": len(texts),
            "total_chars": sum(len(t) for t in texts),
            "estimated_tokens": total_tokens,
            "embedding_dim": self._embedding_dim,
        }
