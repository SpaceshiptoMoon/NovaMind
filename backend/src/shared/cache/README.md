# 缓存系统

NovaMind 缓存系统采用 L1（进程内 LRU）+ L2（Redis）两级架构，为业务模块提供透明的缓存能力。

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  业务层 (Service / Repository)                               │
│    ↓ 调用                                                    │
│  CacheService ── 高级缓存 API (get_or_set / invalidate)      │
│    ↓ 委托                                                    │
│  RedisCache ──── Redis 操作 (get/set/delete/Hash/SCAN)       │
│    ↓ 连接                                                    │
│  Redis Server (单机 / Sentinel / Cluster)                    │
├─────────────────────────────────────────────────────────────┤
│  LRUCache ────── 进程内 LRU + TTL (会话配置/摘要/消息)        │
│  cache_decorator ─ @cache_result / @invalidate_cache 装饰器  │
└─────────────────────────────────────────────────────────────┘
```

**四个核心组件：**

| 组件 | 文件 | 职责 |
|------|------|------|
| `CacheKeyBuilder` | `cache_service.py` | 统一的缓存键生成规则 |
| `CacheService` | `cache_service.py` | 高级缓存 API（空值防护、TTL 抖动、批量失效） |
| `LRUCache` | `lru_cache.py` | 进程内 LRU 缓存（线程安全、TTL 过期） |
| `RedisCache` | `redis_client.py` | 底层 Redis 操作（自动 JSON 序列化、SCAN 批量删除） |
| 装饰器 | `cache_decorator.py` | `@cache_result` 和 `@invalidate_cache` |

---

## CacheKeyBuilder — 缓存键管理

统一管理所有业务缓存键的生成规则，避免键名冲突。

```python
from src.shared.cache.cache_service import CacheKeyBuilder

# 用户
CacheKeyBuilder.user_key(123)               # → "user:123"
CacheKeyBuilder.user_by_username("admin")    # → "user:username:a1b2c3d4"

# 知识空间
CacheKeyBuilder.space_key(5)                # → "space:5"
CacheKeyBuilder.space_stats_key(5)          # → "space:stats:5"

# 知识库
CacheKeyBuilder.kb_key(10)                  # → "kb:10"

# 文档
CacheKeyBuilder.document_key(42)            # → "doc:42"

# 会话
CacheKeyBuilder.session_key("sess_abc")     # → "session:sess_abc"

# 搜索结果
CacheKeyBuilder.search_key(10, "hash123", user_id=1)  # → "search:10:1:hash123"
CacheKeyBuilder.search_key(10, "hash123")              # → "search:10:hash123"

# Token
CacheKeyBuilder.token_blacklist_key("jti_xyz")  # → "token:blacklist:jti_xyz"
CacheKeyBuilder.user_tokens_key(123)            # → "token:user:123"
```

---

## CacheService — 高级缓存 API

提供业务友好的缓存接口，内置空值防护（防穿透）和 TTL 抖动（防雪崩）。

### 基本用法

```python
from src.shared.cache.cache_service import CacheService, CacheKeyBuilder

cache = CacheService(default_ttl=300)  # 默认 TTL 5 分钟

# 简单读写
await cache.set("key", {"name": "test"}, ttl=600)
value = await cache.get("key")

# Cache-Aside 模式（自动回源 + 空值缓存）
user = await cache.get_or_set(
    key=CacheKeyBuilder.user_key(123),
    factory=lambda: user_repo.get(123),  # 缓存未命中时调用
    ttl=7200
)
# factory 返回 None → 缓存 "__NULL__" 标记（60秒），防止穿透

# 批量失效
await cache.invalidate_pattern("user:123:*")

# 删除
await cache.delete("key")
```

### 预设 TTL

| 业务类型 | TTL | 常量 |
|---------|-----|------|
| 用户 | 2 小时 | `DEFAULT_TTLS["user"]` |
| 知识空间 | 2 小时 | `DEFAULT_TTLS["space"]` |
| 知识库 | 1 小时 | `DEFAULT_TTLS["kb"]` |
| 文档 | 30 分钟 | `DEFAULT_TTLS["document"]` |
| 会话 | 24 小时 | `DEFAULT_TTLS["session"]` |
| 搜索结果 | 1 小时 | `DEFAULT_TTLS["search"]` |
| Token 黑名单 | 7 天 | `DEFAULT_TTLS["token"]` |

### 业务快捷方法

```python
cache = CacheService()

# 用户缓存
await cache.cache_user(123, user_dict)
user = await cache.get_cached_user(123)
await cache.invalidate_user_cache(123)   # 失效用户相关所有缓存

# 知识空间缓存
await cache.cache_space(5, space_dict)
space = await cache.get_cached_space(5)
await cache.cache_space_stats(5, stats)  # TTL 10 分钟
await cache.invalidate_space_cache(5)

# 知识库缓存
await cache.cache_kb(10, kb_dict)
kb = await cache.get_cached_kb(10)
await cache.invalidate_kb_cache(10)

# 搜索缓存
await cache.cache_search_result(kb_id=10, query_hash="abc", results=[...], user_id=1)
results = await cache.get_cached_search(kb_id=10, query_hash="abc", user_id=1)
await cache.invalidate_search_cache(kb_id=10)        # 清除所有用户
await cache.invalidate_search_cache(kb_id=10, user_id=1)  # 仅清除特定用户

# Token 黑名单
await cache.add_token_to_blacklist("jti_xyz")
is_blacklisted = await cache.is_token_blacklisted("jti_xyz")
```

### `@cached` 装饰器

`CacheService` 内置的轻量装饰器，用于缓存函数返回值：

```python
from src.shared.cache.cache_service import cached

@cached(prefix="user", ttl=600)
async def get_user(user_id: int):
    return await user_repo.get(user_id)
```

---

## LRUCache — 进程内缓存

线程安全的 LRU 缓存，支持 TTL 过期和最大容量限制。用于高频读取、低频更新的数据。

```python
from src.shared.cache.lru_cache import LRUCache, session_config_cache

# 使用预定义实例
session_config_cache.set("sess_123", config_dict, ttl=300)
config = session_config_cache.get("sess_123")

# 自定义实例
my_cache = LRUCache(max_size=500, default_ttl=600)
my_cache.set("key", value)
my_cache.delete("key")

# 查看统计
stats = my_cache.stats  # {"size": 10, "max_size": 500, "hits": 100, "misses": 20, "hit_rate": 0.83}
```

### 预定义实例

| 实例 | 最大容量 | TTL | 用途 |
|------|---------|-----|------|
| `session_config_cache` | 1000 | 5 分钟 | QA 会话配置 |
| `session_summary_cache` | 500 | 10 分钟 | QA 会话摘要 |
| `session_messages_cache` | 200 | 30 秒 | QA 消息列表 |

---

## 缓存装饰器 — `cache_decorator.py`

基于 Redis 的通用缓存装饰器，适合任意异步/同步函数。

### `@cache_result` — 缓存函数结果

```python
from src.shared.cache.cache_decorator import cache_result

# 基本用法
@cache_result(expire_seconds=3600)
async def get_space(space_id: int):
    return await space_repo.get(space_id)

# 自定义缓存键
@cache_result(
    expire_seconds=600,
    cache_key_prefix="my_module",
    cache_key_func=lambda args, kwargs: f"custom:{args[1]}:{kwargs.get('type', '')}",
)
async def get_data(id: int, type: str = "default"):
    ...

# 跳过特定结果
@cache_result(
    expire_seconds=300,
    skip_cache_func=lambda result: result is None or result.get("error"),
)
async def search(query: str):
    ...
```

### `@invalidate_cache` — 函数执行后失效缓存

```python
from src.shared.cache.cache_decorator import invalidate_cache

@invalidate_cache("user:{user_id}", "user:{user_id}:*")
async def update_user(user_id: int, **kwargs):
    ...
```

---

## RedisCache — 底层 Redis 操作

底层 Redis 客户端，封装了自动 JSON 序列化、SCAN 批量删除、向量相似度搜索等能力。

> 通常通过 `CacheService` 间接使用，不需要直接操作 `RedisCache`。

### 连接模式

```python
# 单机模式（默认）
client = RedisCache(host="localhost", port=6379, db=0)

# 哨兵模式
client = RedisCache(
    mode="sentinel",
    sentinel_hosts=["host1:26379", "host2:26379"],
    sentinel_master="mymaster",
)

# 集群模式
client = RedisCache(
    mode="cluster",
    cluster_hosts=["host1:6379", "host2:6379"],
)
```

### 核心方法

| 方法 | 说明 |
|------|------|
| `get(key)` | 获取值（自动 JSON 反序列化） |
| `set(key, value, expire=None)` | 设置值（自动 JSON 序列化） |
| `delete(*keys)` | 删除键 |
| `exists(*keys)` | 检查键是否存在 |
| `expire(key, ttl)` | 设置过期时间 |
| `incr(key, amount)` | 递增计数器 |
| `mget(*keys)` / `mset(mapping)` | 批量读写 |
| `hgetall(key)` / `hset(key, mapping)` | Hash 操作 |
| `scan_iter(match)` | SCAN 迭代器（生产安全） |
| `delete_by_pattern(pattern)` | 按模式批量删除 |

### 查询向量缓存

用于 RAG 管道的查询结果缓存，支持精确匹配和基于 RediSearch 的向量相似度搜索：

```python
# 缓存查询向量
await redis.cache_query_vector(
    user_id="123", query="什么是AI?", answer="AI是...",
    embedding=[0.1, 0.2, ...], retrieved_docs=[...],
    expire_hours=24
)

# 精确匹配
cached = await redis.get_cached_query_vector(user_id="123", query="什么是AI?")

# 相似查询搜索（需要 Redis Stack）
similar = await redis.find_similar_queries(
    user_id="123", query_embedding=[0.1, 0.2, ...],
    threshold=0.95, limit=5
)

# 创建向量索引
await redis.create_embedding_index(embedding_dim=1024)
```

---

## 配置

在 YAML 配置文件中设置 Redis 连接参数：

```yaml
redis:
  enabled: true
  host: localhost
  port: 6379
  db: 0
  password: null
```

## 降级策略

所有 Redis 操作都有异常捕获，Redis 不可用时自动降级：

- `CacheService.get_or_set()` — 跳过缓存，直接调用 factory
- `@cache_result` — 跳过缓存，直接执行函数
- `RedisCache.get/set/delete` — 返回 None/False/0，不抛异常

## 监控

```python
import logging
logging.getLogger("src.shared.cache").setLevel(logging.INFO)
```

关键指标：`LRUCache.stats`（命中率）、Redis 内存使用、`delete_by_pattern` 删除数量。
