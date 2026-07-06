"""
共享客户端工厂

提供单例模式的客户端实例管理
支持 MinIO、Elasticsearch、Redis 等客户端
使用 asyncio.Lock 保护并发初始化
"""

import asyncio
from typing import Optional

from src.setting.yaml_config import get_config
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class ClientFactory:
    """
    客户端工厂

    管理所有外部服务客户端的单例实例
    支持延迟初始化、依赖注入和异步安全
    """

    _instances = {}
    _async_lock: Optional[asyncio.Lock] = None

    @classmethod
    def _get_async_lock(cls) -> asyncio.Lock:
        """获取异步锁（延迟初始化）"""
        if cls._async_lock is None:
            cls._async_lock = asyncio.Lock()
        return cls._async_lock

    @classmethod
    async def get_minio_client(cls):
        """
        获取 MinIO 客户端单例

        MinIO 客户端构造函数本身是同步的（不涉及网络I/O），
        使用异步锁仅保护并发初始化的安全。

        Returns:
            MinioClient 实例
        """
        if "minio" not in cls._instances:
            async with cls._get_async_lock():
                # 双重检查锁定
                if "minio" not in cls._instances:
                    from src.shared.storage.minio_client import MinioClient

                    config = get_config()
                    cls._instances["minio"] = MinioClient(
                        endpoint=config.minio.endpoint,
                        access_key=config.minio.access_key,
                        secret_key=config.minio.secret_key,
                        secure=config.minio.secure,
                        default_bucket=config.minio.bucket_name,
                        public_endpoint=config.minio.public_endpoint,
                    )
                    logger.info("MinIO 客户端已初始化", endpoint=config.minio.endpoint)

        return cls._instances["minio"]

    @classmethod
    async def get_elasticsearch_client(cls):
        """
        获取 Elasticsearch 客户端单例

        ES 客户端构造函数本身是同步的（不涉及网络I/O），
        使用异步锁仅保护并发初始化的安全。

        Returns:
            ElasticsearchClient 实例
        """
        if "elasticsearch" not in cls._instances:
            async with cls._get_async_lock():
                # 双重检查锁定
                if "elasticsearch" not in cls._instances:
                    from src.shared.storage.elasticsearch_client import ElasticsearchClient

                    config = get_config()
                    # 从配置读取 SSL 参数，默认不使用 SSL
                    es_config = config.elasticsearch
                    use_ssl = getattr(es_config, "use_ssl", False)
                    verify_certs = getattr(es_config, "verify_certs", False)
                    ca_certs = getattr(es_config, "ca_certs", None)
                    cls._instances["elasticsearch"] = ElasticsearchClient(
                        hosts=es_config.hosts,
                        username=es_config.username,
                        password=es_config.password,
                        use_ssl=use_ssl,
                        verify_certs=verify_certs,
                        ca_certs=ca_certs,
                        default_embedding_dim=es_config.default_embedding_dim,
                        default_analyzer=getattr(es_config, "analyzer", "standard"),
                    )
                    logger.info("Elasticsearch 客户端已初始化", hosts=config.elasticsearch.hosts)

        return cls._instances["elasticsearch"]

    @classmethod
    async def get_redis_client(cls):
        """
        获取 Redis 客户端单例（异步）

        使用异步锁保护并发初始化，避免多个协程同时创建连接。

        Returns:
            RedisCache 实例
        """
        if "redis" not in cls._instances:
            async with cls._get_async_lock():
                if "redis" not in cls._instances:
                    from src.shared.cache.redis_client import RedisCache

                    config = get_config()
                    redis_config = getattr(config, 'redis', None)

                    # 确定 Redis 运行模式
                    mode = "standalone"
                    sentinel_hosts = None
                    sentinel_master = None
                    cluster_hosts = None

                    if redis_config:
                        if hasattr(redis_config, 'sentinel_hosts') and redis_config.sentinel_hosts:
                            mode = "sentinel"
                            sentinel_hosts = [h.strip() for h in redis_config.sentinel_hosts.split(",") if h.strip()]
                            sentinel_master = getattr(redis_config, 'sentinel_master', 'mymaster')
                        elif hasattr(redis_config, 'cluster_hosts') and redis_config.cluster_hosts:
                            mode = "cluster"
                            cluster_hosts = [h.strip() for h in redis_config.cluster_hosts.split(",") if h.strip()]

                    client = RedisCache(
                        host=getattr(redis_config, 'host', 'localhost'),
                        port=getattr(redis_config, 'port', 6379),
                        db=getattr(redis_config, 'db', 0),
                        password=getattr(redis_config, 'password', None),
                        max_connections=getattr(redis_config, 'max_connections', 20),
                        mode=mode,
                        sentinel_hosts=sentinel_hosts,
                        sentinel_master=sentinel_master,
                        cluster_hosts=cluster_hosts,
                    )
                    await client.connect()

                    cls._instances["redis"] = client

                    logger.info("Redis 客户端已初始化", mode=mode, host=getattr(redis_config, 'host', 'localhost'))

        return cls._instances["redis"]

    @classmethod
    async def close_all(cls):
        """
        关闭所有客户端实例并清理

        按安全顺序依次关闭各客户端，最后清空实例字典。
        """
        # 先关闭 Redis（可能有连接池需要释放）
        redis_client = cls._instances.get("redis")
        if redis_client:
            try:
                await redis_client.disconnect()
            except Exception as e:
                logger.warning("关闭 Redis 客户端失败", error=str(e))

        # 关闭 Elasticsearch
        es_client = cls._instances.get("elasticsearch")
        if es_client:
            try:
                await es_client.close()
            except Exception as e:
                logger.warning("关闭 Elasticsearch 客户端失败", error=str(e))

        # MinIO 无异步 close，跳过

        # 清空实例字典
        async with cls._get_async_lock():
            cls._instances.clear()

        logger.info("所有客户端实例已关闭并清理")

    @classmethod
    async def reset(cls):
        """
        重置所有客户端实例（用于测试）
        """
        async with cls._get_async_lock():
            cls._instances.clear()
        logger.info("所有客户端实例已重置")


# 便捷函数
async def get_minio_client():
    """获取 MinIO 客户端单例"""
    return await ClientFactory.get_minio_client()


async def get_elasticsearch_client():
    """获取 Elasticsearch 客户端单例"""
    return await ClientFactory.get_elasticsearch_client()


