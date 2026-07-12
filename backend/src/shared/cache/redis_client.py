import base64
import hashlib
import json
from typing import Optional, List, Dict, Any, Union, AsyncIterator
import redis.asyncio as redis
from redis.exceptions import ConnectionError, RedisError

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class RedisCache:
    """
    Redis缓存客户端

    支持功能：
    - 基础 String 操作（get/set/delete）
    - 带 TTL 的缓存
    - JSON 序列化
    - Hash 操作
    - 批量删除（SCAN）
    - 查询向量缓存
    - 哨兵和集群模式支持
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_connections: int = 20,
        # 集群和哨兵支持
        mode: str = "standalone",  # standalone, sentinel, cluster
        sentinel_hosts: Optional[List[str]] = None,
        sentinel_master: Optional[str] = None,
        cluster_hosts: Optional[List[str]] = None,
    ):
        """
        初始化Redis客户端

        Args:
            host: Redis主机地址（standalone 模式）
            port: Redis端口
            db: Redis数据库编号
            password: Redis密码
            max_connections: 最大连接数
            mode: 运行模式（standalone/sentinel/cluster）
            sentinel_hosts: 哨兵地址列表（如 ["host1:26379", "host2:26379"]）
            sentinel_master: 哨兵监视的主节点名称
            cluster_hosts: 集群节点地址列表（如 ["host1:6379", "host2:6379"]）
        """
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.max_connections = max_connections
        self.mode = mode
        self.sentinel_hosts = sentinel_hosts
        self.sentinel_master = sentinel_master
        self.cluster_hosts = cluster_hosts
        self.redis_client = None
        self._connection_pool = None

    async def connect(self):
        """
        建立Redis连接（支持单机、哨兵、集群模式）
        """
        try:
            if self.mode == "sentinel" and self.sentinel_hosts:
                # 哨兵模式
                from redis.asyncio.sentinel import Sentinel

                sentinel = Sentinel(
                    [(h.split(":")[0], int(h.split(":")[1])) for h in self.sentinel_hosts],
                    socket_timeout=5,
                )
                self.redis_client = sentinel.master_for(
                    self.sentinel_master,
                    socket_timeout=5,
                    password=self.password,
                    db=self.db,
                )
                logger.info(
                    f"成功连接到Redis哨兵集群",
                    sentinel_hosts=self.sentinel_hosts,
                    master=self.sentinel_master,
                )

            elif self.mode == "cluster" and self.cluster_hosts:
                # 集群模式
                from redis.asyncio.cluster import RedisCluster

                self.redis_client = RedisCluster(
                    startup_nodes=[{"host": h.split(":")[0], "port": int(h.split(":")[1])} for h in self.cluster_hosts],
                    password=self.password,
                    max_connections=self.max_connections,
                    decode_responses=False,
                )
                logger.info(
                    f"成功连接到Redis集群",
                    cluster_hosts=self.cluster_hosts,
                )

            else:
                # 单机模式
                self._connection_pool = redis.ConnectionPool(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    max_connections=self.max_connections,
                    retry_on_timeout=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
                self.redis_client = redis.Redis(connection_pool=self._connection_pool)
                logger.info(f"成功连接到Redis: {self.host}:{self.port}/{self.db}")

            # 测试连接
            await self.redis_client.ping()

        except ConnectionError as e:
            logger.error(f"连接Redis失败: {e}")
            raise
        except Exception as e:
            logger.error(f"Redis连接错误: {e}")
            raise

    async def disconnect(self):
        """
        断开Redis连接
        """
        if self.redis_client:
            try:
                await self.redis_client.close()
                if self._connection_pool:
                    await self._connection_pool.aclose()
                logger.info("Redis连接已断开")
            except Exception as e:
                logger.error(f"断开Redis连接时出错: {e}")

    # ============================================================
    # 基础 String 操作
    # ============================================================

    async def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值（自动 JSON 反序列化）
        :param key: 缓存键
        :return: 缓存值，不存在返回 None
        """
        try:
            if not self.redis_client:
                await self.connect()

            value = await self.redis_client.get(key)
            if value is None:
                return None

            # 尝试 JSON 反序列化
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                # 如果不是 JSON，返回原始字符串
                if isinstance(value, bytes):
                    return value.decode('utf-8')
                return value
        except RedisError as e:
            logger.warning(f"获取缓存降级，键: {key}, 错误: {e}")
            return None

    async def set(
        self,
        key: str,
        value: Any,
        expire: Optional[int] = None
    ) -> bool:
        """
        设置缓存值（自动 JSON 序列化）
        :param key: 缓存键
        :param value: 缓存值
        :param expire: 过期时间（秒），None 表示永不过期
        :return: 是否成功
        """
        try:
            if not self.redis_client:
                await self.connect()

            # JSON 序列化（非字符串/字节类型统一使用 json.dumps，保证 get 时类型一致）
            if not isinstance(value, (str, bytes)):
                value = json.dumps(value, ensure_ascii=False)

            if expire:
                await self.redis_client.setex(key, expire, value)
            else:
                await self.redis_client.set(key, value)
            return True
        except RedisError as e:
            logger.warning(f"设置缓存降级，键: {key}, 错误: {e}")
            return False

    async def setex(self, key: str, ttl: int, value: Any) -> bool:
        """
        设置带过期时间的缓存值
        :param key: 缓存键
        :param ttl: 过期时间（秒）
        :param value: 缓存值
        :return: 是否成功
        """
        return await self.set(key, value, expire=ttl)

    async def delete(self, *keys: str) -> int:
        """
        删除一个或多个键
        :param keys: 要删除的键
        :return: 删除的键数量
        """
        try:
            if not self.redis_client:
                await self.connect()

            if not keys:
                return 0

            result = await self.redis_client.delete(*keys)
            return result
        except RedisError as e:
            logger.warning(f"删除缓存降级，键: {keys}, 错误: {e}")
            return 0

    async def exists(self, *keys: str) -> int:
        """
        检查键是否存在
        :param keys: 要检查的键
        :return: 存在的键数量
        """
        try:
            if not self.redis_client:
                await self.connect()

            return await self.redis_client.exists(*keys)
        except RedisError as e:
            logger.warning(f"检查键存在降级，键: {keys}, 错误: {e}")
            return 0

    async def expire(self, key: str, ttl: int) -> bool:
        """
        设置键的过期时间
        :param key: 缓存键
        :param ttl: 过期时间（秒）
        :return: 是否成功
        """
        try:
            if not self.redis_client:
                await self.connect()

            return await self.redis_client.expire(key, ttl)
        except RedisError as e:
            logger.warning(f"设置过期时间降级，键: {key}, 错误: {e}")
            return False

    async def ttl(self, key: str) -> int:
        """
        获取键的剩余过期时间
        :param key: 缓存键
        :return: 剩余秒数，-1 表示永不过期，-2 表示不存在
        """
        try:
            if not self.redis_client:
                await self.connect()

            return await self.redis_client.ttl(key)
        except RedisError as e:
            logger.warning(f"获取TTL降级，键: {key}, 错误: {e}")
            return -2

    async def incr(self, key: str, amount: int = 1) -> int:
        """
        递增计数器
        :param key: 缓存键
        :param amount: 递增量
        :return: 递增后的值
        """
        try:
            if not self.redis_client:
                await self.connect()

            return await self.redis_client.incrby(key, amount)
        except RedisError as e:
            logger.warning(f"递增降级，键: {key}, 错误: {e}")
            return 0

    async def decr(self, key: str, amount: int = 1) -> int:
        """
        递减计数器
        :param key: 缓存键
        :param amount: 递减量
        :return: 递减后的值
        """
        return await self.incr(key, -amount)

    # ============================================================
    # 批量操作
    # ============================================================

    async def mget(self, *keys: str) -> List[Optional[Any]]:
        """
        批量获取多个键的值
        :param keys: 缓存键列表
        :return: 值列表
        """
        try:
            if not self.redis_client:
                await self.connect()

            values = await self.redis_client.mget(keys)
            results = []
            for value in values:
                if value is None:
                    results.append(None)
                else:
                    try:
                        results.append(json.loads(value))
                    except (json.JSONDecodeError, TypeError):
                        if isinstance(value, bytes):
                            results.append(value.decode('utf-8'))
                        else:
                            results.append(value)
            return results
        except RedisError as e:
            logger.warning(f"批量获取降级，键: {keys}, 错误: {e}")
            return [None] * len(keys)

    async def mset(self, mapping: Dict[str, Any], expire: Optional[int] = None) -> bool:
        """
        批量设置多个键值对
        :param mapping: 键值对字典
        :param expire: 过期时间（秒）
        :return: 是否成功
        """
        try:
            if not self.redis_client:
                await self.connect()

            # 序列化所有值
            serialized = {}
            for key, value in mapping.items():
                if not isinstance(value, (str, bytes)):
                    serialized[key] = json.dumps(value, ensure_ascii=False)
                else:
                    serialized[key] = value

            await self.redis_client.mset(serialized)

            # 设置过期时间
            if expire:
                for key in mapping.keys():
                    await self.redis_client.expire(key, expire)

            return True
        except RedisError as e:
            logger.warning(f"批量设置降级，错误: {e}")
            return False

    # ============================================================
    # 模式匹配与批量删除
    # ============================================================

    async def scan_iter(
        self,
        match: str,
        count: int = 100
    ) -> AsyncIterator[str]:
        """
        扫描匹配的键（使用 SCAN 命令，生产环境安全）
        :param match: 匹配模式（如 "user:*"）
        :param count: 每次扫描的数量
        :return: 键的异步迭代器
        """
        try:
            if not self.redis_client:
                await self.connect()

            async for key in self.redis_client.scan_iter(match=match, count=count):
                if isinstance(key, bytes):
                    yield key.decode('utf-8')
                else:
                    yield key
        except RedisError as e:
            logger.warning(f"扫描键降级，模式: {match}, 错误: {e}")
            return

    async def delete_by_pattern(self, pattern: str, batch_size: int = 100) -> int:
        """
        批量删除匹配模式的所有键
        :param pattern: 匹配模式（如 "space:123:*"）
        :param batch_size: 每批删除的数量
        :return: 删除的总键数
        """
        deleted_count = 0
        try:
            if not self.redis_client:
                await self.connect()

            keys_to_delete = []

            async for key in self.scan_iter(pattern):
                keys_to_delete.append(key)
                if len(keys_to_delete) >= batch_size:
                    deleted_count += await self.delete(*keys_to_delete)
                    keys_to_delete = []

            # 删除剩余的键
            if keys_to_delete:
                deleted_count += await self.delete(*keys_to_delete)

            if deleted_count > 0:
                logger.info(f"批量删除缓存，模式: {pattern}, 删除数量: {deleted_count}")

            return deleted_count
        except RedisError as e:
            logger.warning(
                "批量删除降级，已处理部分键",
                pattern=pattern,
                deleted=deleted_count,
                error=str(e),
            )
            return deleted_count

    async def keys_count(self, pattern: str = "*") -> int:
        """
        统计匹配模式的键数量（使用 SCAN）
        :param pattern: 匹配模式
        :return: 键数量
        """
        try:
            if not self.redis_client:
                await self.connect()

            count = 0
            async for _ in self.scan_iter(pattern):
                count += 1
            return count
        except RedisError as e:
            logger.warning(f"统计键数量降级，模式: {pattern}, 错误: {e}")
            return 0

    # ============================================================
    # Hash 操作
    # ============================================================

    async def hgetall(self, key: str) -> Dict:
        """
        获取Hash中的所有字段
        :param key: 键
        :return: 字段字典
        """
        try:
            if not self.redis_client:
                await self.connect()

            data = await self.redis_client.hgetall(key)
            if not data:
                return {}

            # 转换bytes为str
            result = {}
            for k, v in data.items():
                if isinstance(k, bytes):
                    k = k.decode("utf-8")
                if isinstance(v, bytes):
                    v = v.decode("utf-8")
                result[k] = v

            return result
        except RedisError as e:
            logger.warning(f"获取Hash降级，键: {key}, 错误: {e}")
            return {}

    async def hset(self, key: str, mapping: Dict) -> bool:
        """
        设置Hash字段
        :param key: 键
        :param mapping: 字段映射
        :return: 是否成功
        """
        try:
            if not self.redis_client:
                await self.connect()

            result = await self.redis_client.hset(key, mapping=mapping)
            return True
        except RedisError as e:
            logger.warning(f"设置Hash降级，键: {key}, 错误: {e}")
            return False

    # === 查询向量缓存方法 ===

    async def cache_query_vector(
        self,
        user_id: str,
        query: str,
        answer: str,
        embedding: List[float],
        retrieved_docs: List,
        expire_hours: int = 24,
    ) -> bool:
        """
        缓存查询查询结果及其嵌入向量（用于精确匹配和相似查询）
        :param user_id: 用户ID
        :param query: 查询文本
        :param answer: RAG结果
        :param embedding: 查询的嵌入向量
        :param retrieved_docs: 检索到的文档列表
        :param expire_hours: 过期时间（小时）
        :return: 是否缓存成功
        """
        import numpy as np

        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        key = f"query_vector:{user_id}:{query_hash}"

        # 将所有数据存储在一个Hash中
        data = {
            "query": query,
            "answer": answer,
            "embedding": base64.b64encode(np.array(embedding, dtype=np.float32).tobytes()).decode("ascii"),
            "retrieved_docs": json.dumps(retrieved_docs, ensure_ascii=False) if retrieved_docs else "[]",
            "user_id": user_id,
            "query_hash": query_hash,
        }

        try:
            if not self.redis_client:
                await self.connect()

            await self.hset(key, mapping=data)
            await self.redis_client.expire(key, expire_hours * 3600)
            return True
        except RedisError as e:
            logger.warning(f"缓存查询向量降级，键: {key}, 错误: {e}")
            return False

    async def get_cached_query_vector(self, user_id: str, query: str) -> Optional[Dict]:
        """
        获取缓存的查询向量数据（用于精确匹配）
        :param user_id: 用户ID
        :param query: 查询文本
        :return: 包含query、answer、embedding等的字典，如果不存在返回None
        """
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        key = f"query_vector:{user_id}:{query_hash}"

        try:
            if not self.redis_client:
                await self.connect()

            data = await self.hgetall(key)
            if not data:
                return None

            # 转换bytes为适当类型
            import numpy as np

            result = {}
            for k, v in data.items():
                if k == "embedding":
                    # 处理 base64 编码的嵌入向量
                    if isinstance(v, bytes):
                        v = v.decode("utf-8")
                    result[k] = np.frombuffer(base64.b64decode(v), dtype=np.float32).tolist()
                elif k == "retrieved_docs":
                    # 反序列化 JSON 文档列表
                    if isinstance(v, bytes):
                        v = v.decode("utf-8")
                    result[k] = json.loads(v)
                else:
                    result[k] = v
            return result
        except RedisError as e:
            logger.warning(f"获取查询向量缓存降级，键: {key}, 错误: {e}")
            return None

    async def find_similar_queries(
        self,
        user_id: str,
        query_embedding: List[float],
        threshold: float = 0.95,
        limit: int = 5,
    ) -> List[Dict]:
        """
        查找相似的历史查询（基于embedding的近似缓存）
        :param user_id: 用户ID
        :param query_embedding: 查询嵌入向量
        :param threshold: 相似度阈值
        :param limit: 返回结果数量
        :return: 相似查询列表
        """
        try:
            import numpy as np
            from redis.commands.search.query import Query

            # 检查是否启用了RediSearch
            if not hasattr(self.redis_client, "ft"):
                logger.warning(
                    "Redis Stack (RediSearch) not enabled, skipping vector similarity search"
                )
                return []

            # 确保embedding不为空
            if not query_embedding or len(query_embedding) == 0:
                logger.warning("Query embedding is empty")
                return []

            # 索引名称
            index_name = "query_vector_idx"

            # 正确构造 filter 表达式
            user_filter = f"@user_id:{{{user_id}}}"  # 注意三重花括号！

            search_query = (
                Query(
                    f"{user_filter} => [KNN {limit} @embedding $embedding AS vector_score]"
                )
                .return_fields("query", "retrieved_docs", "answer", "query_hash")
                .add_param(
                    "embedding",
                    np.array(query_embedding, dtype=np.float32).tobytes(),
                )
                .dialect(2)
            )

            results = await self.redis_client.ft(index_name).search(search_query)

            # 处理搜索结果
            similar_queries = []
            for doc in results.docs:
                # 注意：Redis的相似度分数，需要转换为距离
                # 对于余弦相似度，距离 = 1 - 相似度
                similarity = 1.0 - float(doc.vector_score)

                if similarity >= threshold:
                    # 直接用 query_hash 构建缓存键读取数据，避免二次哈希
                    key = f"query_vector:{user_id}:{doc.query_hash}"
                    raw_data = await self.hgetall(key)
                    if raw_data:
                        # 解析缓存的向量数据
                        retrieved_docs_raw = raw_data.get("retrieved_docs", "[]")
                        if isinstance(retrieved_docs_raw, bytes):
                            retrieved_docs_raw = retrieved_docs_raw.decode("utf-8")
                        vector_data = {
                            "query": raw_data.get("query", b"").decode("utf-8") if isinstance(raw_data.get("query"), bytes) else raw_data.get("query", ""),
                            "answer": raw_data.get("answer", b"").decode("utf-8") if isinstance(raw_data.get("answer"), bytes) else raw_data.get("answer", {}),
                            "retrieved_docs": json.loads(retrieved_docs_raw),
                        }
                        similar_queries.append(
                            {
                                "query": vector_data.get("query", ""),
                                "answer": vector_data.get("answer", {}),
                                "retrieved_docs": vector_data.get("retrieved_docs", []),
                                "similarity": similarity,
                            }
                        )

            # 按相似度排序（从高到低）
            similar_queries.sort(key=lambda x: x["similarity"], reverse=True)
            return similar_queries[:limit]

        except Exception as e:
            logger.error(f"Vector similarity search failed: {e}")
            return []


    async def create_embedding_index(
        self,
        embedding_dim: int,
        index_name: str = "query_vector_idx"
    ) -> bool:
        """
        创建Redis向量索引
        :param embedding_dim: 嵌入向量维度
        :param index_name: 索引名称
        :return: 是否创建成功
        """
        try:
            from redis.commands.search.field import VectorField, TagField, TextField

            # 检查是否启用了RediSearch
            if not hasattr(self.redis_client, "ft"):
                logger.warning("Redis Stack (RediSearch) not enabled, skipping index creation")
                return False

            # 创建索引，包含向量字段和标量字段
            await self.redis_client.ft(index_name).create_index(
                fields=[
                        TagField("user_id"),
                        TextField("query_hash"),
                        TextField("answer"),
                        VectorField(
                            "embedding",
                            "FLAT",  # 算法
                            {
                                "TYPE": "FLOAT32",
                                "DIM": embedding_dim,
                                "DISTANCE_METRIC": "COSINE",
                                "INITIAL_CAP": 1000,
                            }
                        )
                    ]
                )
                    

            
            logger.info(f"Redis向量索引创建成功: {index_name}")
            return True
        except Exception as e:
            if "index already exists" in str(e).lower():
                logger.info(f"Redis向量索引已存在: {index_name}")
                return True
            else:
                logger.error(f"创建Redis向量索引失败: {e}")
                return False


async def get_redis_client() -> RedisCache:
    """
    获取全局Redis客户端实例（支持单机、哨兵、集群模式）

    委托给 ClientFactory 统一管理单例
    """
    from novamind.shared.clients import ClientFactory
    return await ClientFactory.get_redis_client()


async def close_redis_connection():
    """
    关闭全局Redis连接
    """
    from novamind.shared.clients import ClientFactory
    await ClientFactory.close_all()
