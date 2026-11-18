# 缓存优化交接文档（2026-11-14，全部批次完成）

> 2026-11-18 状态更新：本批次 8 个实施提交已全部推送 origin/main，下文『未推送』为成文时快照。

> 背景：全项目缓存设计盘点后按批次实施。盘点结论与 21 项热点清单见 memory
> `cache-design-audit-2026-11.md`。

## 状态一句话

**全部五批次已实施并提交**（本地 main 未推送，共 8 个实施提交），单测 2294 passed + 架构门禁全绿，**并已完成真机验收**（本机 :8100 后端重启加载新代码，缓存命中/失效时序/安全红线均实测通过）。

## 用户目标完成度

原目标：「执行缓存优化；最后检查缓存是否有效；测试是否出现缓存不一致」。

| 要求 | 状态 | 证据 |
|---|---|---|
| 执行缓存优化 | ✅ 五批次全完成 | 提交栈见下 |
| 缓存有效性 | ✅ 单测 + 真机双层 | 单测：命中零 SQL/零凭证查询断言；真机：`/health/detailed` 的 cache_stats 实测 `notif: {hit:2, miss:2, hit_rate:0.5}`，`auth:status:1`、`notif:unread:1` 键真实写入 Redis，快照 TTL 实测递减不重写（miss 回填 60s → 命中后 58s） |
| 缓存不一致 | ✅ 单测 + 真机双层 | 单测：提交后二次失效清脏回填、失效等待进行中构造、请求级缓存跨请求不泄漏、黑名单合并查询 10 组对拍；真机：登出后旧 token 立即 401（jti 实时红线） |

## 提交栈（本批次全部未推送）

| 提交 | 内容 |
|---|---|
| fdfb5b1f | 批次1：模型客户端 per-key 锁重构 + 删短期记忆无消费 COUNT |
| d376f610 | 批次2：认证链快照缓存（TTL 60s）+ 失效双保险（立即删 + after_commit 提交后二次删） |
| 3fb07659 | 交接文档（初版） |
| 42ad4abd | 批次2残留：黑名单 EXISTS+GET 合并为一次 pipeline（HTTP/WS 两链路） |
| 5d59c018 | 删零消费缓存框架（约 -1700 行），新增 helpers.get_or_load/invalidate/cache_stats |
| 09cc91be | 批次3：成员/KB 校验请求级 contextvar 去重 |
| aeaab5ff | 批次4：预签名/查询向量/查询改写三处缓存 |
| 89ed9037 | 批次5：页面级短 TTL（六桶/会话中心/未读数/看板/wiki 统计）+ ES 索引探测缓存 |
| 64373775 | /health/detailed 暴露 cache_stats（命中率运维观测入口） |
| 5009b272 | **正确性修复：emb/rw 缓存键补客户端配置签名**（用户指出串键漏洞后）——BaseLLM/BaseEmbedding 基类加 cache_signature()，同名模型跨提供商/归一化开关不同不再静默串键 |

## 缓存键的配置签名（重要设计）

`emb`/`rw` 缓存键里的客户端身份**不是裸模型名**，而是 `client_cache_signature()`（`base_model.py`）＝ md5(base_url | model | 子类追加配置)。原因：同名模型在不同提供商（DashScope vs 自建 vLLM）下向量/输出完全不同，只按模型名隔离会静默串键——维度恰好相同时是错误结果而非报错。新增影响输出的构造级配置时，记得往 `self._cache_sig_extra` 追加。当前实例（Redis 8.0.5 MSYS2 构建）实测无 RediSearch Query Engine、vectorset 模块残缺不可用——向量检索只能由 ES 承担，emb 缓存仅依赖 String GET/SET，与此无关。

## 实施中的方案修正（相对最初盘点方案，均有依据）

1. **批次 3 的成员/KB Redis 跨请求缓存未做**：校验函数返回 ORM 对象（`SpaceMember`/`KnowledgeBase`），跨请求缓存必须改返回形状波及全部下游；且 Redis GET 与 MySQL 主键点查的 RTT 同量级，替换无净收益；成员权限放宽方向的 60s 窗口未获用户同意。只做了请求级去重（真减少往返、零语义变化）。若未来要做：先改返回形状为 dict，并获权限取舍确认。
2. **预签名缓存从 `MinioClient.get_file_url` 迁出到独立入口 `shared/storage/url_signing.py`**：原做法让底层客户端封装依赖缓存策略层，形成 `helpers → client_factory → minio_client → helpers` 静态环（被 import 无环门禁 R1 拦截，属真实架构信号而非误报）。调用点（document_query_service 4 处 + attachment_presign 1 处）改调 `presigned_get_url`。
3. **helpers 对 client_factory 用函数内懒 import**（`_get_redis_client`）：同环问题的另一半；门禁把函数内 import 也计边（ast.walk 全量建模，如实反映运行时依赖）。
4. **pydantic 模型返回值缓存必须 `model_dump(mode="json")`**：`json.dumps` 不能直接序列化 BaseModel；会话中心命中后 `model_validate` 重建模型对象，对调用方保持单一返回形状。
5. **auth 快照缓存没有走 helpers 计数器**（批次 2 的实现是 user_repository 内手写路径），所以 `/health/detailed` 的 cache_stats 没有 `auth:status` 前缀——键与 TTL 已实测（Redis 键 + TTL 递减验证），如需纳入统计可后续迁移到 get_or_load。

## 真机验收记录（2026-11-14，本机 :8100）

后端重启（taskkill 旧进程 → `.venv/Scripts/python.exe main.py` 后台拉起，启动 2.17s healthy）：

1. 登录 → 连打认证接口 → Redis 出现 `auth:status:1`；3 次请求后 TTL 从 60 递减到 58 且不重写——**miss 回填一次、命中路径零回写**实锤。
2. 未读数打 4 次 → cache_stats `notif: {hit:2, miss:2, hit_rate:0.5}`——回源与命中各半，计数准确。
3. 登出 → 旧 token 立即 401（jti 黑名单实时，未被缓存）；重新登录正常。
4. `/health/detailed` 新增 `cache_stats` 字段（提交 64373775），持续观测命中率入口。

注意：cache_stats 是进程内计数；当前部署 workers=1（单进程）无歧义，多 worker 部署时各进程各计各的。

## 各缓存的键 / TTL / 失效速查

| 前缀 | TTL | 失效 | 位置 |
|---|---|---|---|
| `auth:status:{uid}` | 60s | 写入口统一失效 + 提交后二次删 | user_repository:297 |
| `sesscenter:{uid}:{limit}` | 60s | 无（每轮对话 touch updated_at） | agent_service:527 |
| `notif:unread:{uid}` | 30s | send/mark_read/mark_all_read 即时 | notification_service |
| `kbstats:{kb_id}` / `kbstats:batch:{sig}` | 60s | 无（前端轮询场景容忍） | document_repository |
| `gapstats:{space}:{sig}` | 300s | 无 | space_stats_service |
| `wikistats:{space_id}` | 60s | 无 | wiki_repository |
| `presign:{bucket}:{object}:{expires}` | expires-600 | 无（路径不可变） | url_signing |
| `emb:{md5(model)}:{md5(text)}` | 1800s | 无（确定性调用） | retrieval_engine._embed_cached |
| `rw:{strategy}:{config_sig}:{query}` | 600s | 无（TTL 收敛模板变更） | search_service |
| `search:{kb_id}:...` | 3600s | 文档生命周期/标签/wiki 重建显式清扫（存量） | retrieval_engine |
| 用户/空间/哈希去重/RBAC/AppGate | 存量不变 | 见各仓储 | 存量 |

## 遗留与建议

1. **存量负收益缓存未修**：`user:id` ORM 缓存命中路径 3 条 SQL（refresh+selectin），仍在（`get_user_by_id`）——快照已绕开它，但该路径的命中分支建议后续清理。
2. **`soft_delete` 以改名后 username 调失效** → `user:name:{旧名}` 孤儿键残留至 TTL（行为安全）。
3. **成员 Redis 缓存**：见「方案修正 1」，需要产品级确认权限延迟窗口后再动。
4. **命中率观测**：`/health/detailed` 的 cache_stats；命中率长期 <30% 的缓存应砍掉（README 已写）。
5. **多 worker 部署**：cache_stats 各进程各计各的；若需要全局命中率，把 _stats 迁 Redis（INCR）即可。

## 坑清单（新增）

8. `storage/__init__` re-export 了 minio_client/elasticsearch_client——任何 shared/storage 顶层模块反向 import shared.cache.helpers 都会成环（本批次实录，门禁拦截）。
9. `client_factory.get_redis_client` 是 **async** 函数，懒封装时别丢 await。
10. uvicorn factory + workers>1 时 cache_stats 各 worker 独立；本机默认 workers=1。

## 坑清单（沿用初版，仍然有效）

1. Windows 下 `read_text/write_text` 翻行尾，改行尾敏感文件用 bytes。
2. SQLite BigInteger 主键不自增，测试显式给 id。
3. rollback expire ORM 属性 → AsyncSession 下访问触发 MissingGreenlet，提前求值。
4. 测试注假 Redis：`ClientFactory._instances["redis"]` 单例口。
5. `create_from_credentials` 是同步回调，模型客户端时序测试挂点在凭证查询。
6. `before_cursor_execute` 回调 6 参数。
7. pytest 无 pytest-timeout，`--timeout` 不可用。

## 接手快速开始

```bash
cd backend
# 全量回归（基线：2294 passed + 架构门禁全绿）
.venv/Scripts/python -m pytest tests/shared/ tests/features/ tests/core/ tests/engines/rag/ tests/architecture/ -q
# 真机观测：起后端后打几个认证/通知接口，再看命中率
curl -s http://127.0.0.1:8100/health/detailed | jq .cache_stats
```

推送前提醒：本批次 9 个提交全部未推送（本地 main 领先 origin/main 33 个提交，含之前的 24 个），按仓库惯例攒批审查后统一推送。
