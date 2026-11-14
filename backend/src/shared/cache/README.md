# 缓存模块

本目录只有两样东西：

| 文件 | 职责 |
|------|------|
| `redis_client.py` | `RedisCache`：Redis 连接（单机/哨兵/集群）、JSON 序列化存取、Hash、SCAN 模式删除 |
| `helpers.py` | cache-aside 薄助手：`get_or_load` / `invalidate` / `cache_stats` |

客户端实例统一经 `novamind.shared.storage.client_factory.get_redis_client()` 获取。

## 用法

```python
from novamind.shared.cache.helpers import get_or_load, invalidate

async def get_kb_stats(self, kb_id: int) -> dict:
    return await get_or_load(
        f"kbstats:{kb_id}", 60, lambda: self._query_kb_stats(kb_id)
    )

async def rename_kb(self, kb_id: int, name: str) -> None:
    async with self.session.begin_nested():
        ...
    await invalidate(f"kb:{kb_id}")
```

## 约定

1. **只做 cache-aside，写路径删缓存，不更新缓存。** 并发双写下「更新缓存」会乱序，删键是幂等的。
2. **每个缓存必须有 TTL。** 主动失效会漏挂、会失败；TTL 是脏读的上限，按业务容忍度定。
3. **缓存层故障必须降级，不得阻断主路径。** `get_or_load` 读失败直接回源、写失败本次不缓存；`invalidate` 失败只告警。安全语义的检查（token 撤销黑名单）不属于缓存，不走本模块。
4. **失效紧挨着写操作手写。** 不做集中式失效注册表——漏挂时这种写法最容易在 review 中被发现。能只靠 TTL 的缓存就不要写失效代码。
5. **repository 不提交事务，失效发生在 commit 之前。** 并发读可能在失效之后、提交之前回填旧值。对脏读敏感的缓存须在提交后再删一次，做法见 `user_repository._schedule_post_commit_invalidation`。
6. **值须可 JSON 序列化。** 读回的是 dict/list/基本类型；回源结果为 `None` 时不缓存。
7. **不缓存可变对象引用，不缓存 ORM 对象。** 缓存纯数据快照。
8. **明文凭证不得落 Redis**，只允许驻留进程内存。
9. **向量类缓存的键必须包含模型名。** 换模型后维度不同，旧向量会让检索直接出错。

## 观测

`cache_stats()` 返回按键前缀聚合的命中/回源/故障次数与命中率（进程内计数，多进程各计各的）。命中率长期偏低的缓存说明键设计或 TTL 有问题，应调整或移除。
