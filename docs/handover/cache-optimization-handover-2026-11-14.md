# 缓存优化批次交接文档（2026-11-14）

> 背景：全项目缓存设计盘点后按五批次方案实施。本文档交接已完成部分、
> 未完成清单与全部实施依据。盘点结论全文见 memory
> `cache-design-audit-2026-11.md`（21 项热点分级清单与行号）。

## 状态一句话

五批次中的 **批次 1（模型客户端锁重构）与批次 2（认证链快照缓存）已实施并提交**（本地 main，未推送），各自带有效性 + 缓存一致性测试；批次 3-5 与死代码清理未动；**验收仅到单测级（假 Redis + SQLite 内存库），未做真机（真实 Redis/MySQL/运行后端）验证，无命中率数据**。

## 用户目标与完成度对照

原始目标：「开始执行，最后要检查缓存是否有效，并测试是否会出现缓存不一致等问题」。

| 要求 | 状态 | 证据位置 |
|---|---|---|
| 执行缓存优化 | 2/5 批次完成 | 提交 fdfb5b1f、d376f610 |
| 检查缓存是否有效 | 已完成部分有效（单测级） | 每批次测试含「命中零 SQL/零凭证查询」断言；无真机命中率数据 |
| 测试缓存不一致 | 已完成批次已测（单测级） | 「提交后二次失效清脏回填」「失效等待构造」「回滚语义」等 12 个用例 |

## 已完成明细

### 提交 fdfb5b1f —— 批次 1：模型客户端 per-key 锁重构 + COUNT 死代码删除

- `backend/src/features/user/services/model_config_service.py`：全局单锁拆 per-key
  锁（`_key_locks`:73 / `_get_key_lock`:80 / `_locks_guard`:74），快路径无锁读
  （`_get_client_by_model`:532），过期清理改 2% 概率触发（`_CLEANUP_PROBABILITY`:75，
  原每次调用全表扫描）；**失效 `_clear_client_cache_global`:93 必须拿同一把 key
  锁**，防「构造进行中失效先删、构造完成旧客户端写回复活」竞态。
- `backend/src/features/agent/repository/agent_repository.py`：删除
  `list_recent_by_conversation(_after)` 的 COUNT 子查询（全部调用方以 `_total`/`_`
  丢弃），签名改为返回 `list`；4 处源码调用方 + 4 个测试文件 mock 同步。
- 新测试 `tests/features/user/test_model_client_cache_locks.py`（5 用例）：
  同 key 50 并发 singleflight、不同 key 凭证查询时间重叠、失效等待进行中构造、
  命中不查凭证、过期重建关闭旧客户端。

### 提交 d376f610 —— 批次 2：认证链快照缓存

- `user_repository.py`：`get_auth_status_cached`:297（纯 dict 快照，TTL 60s，
  命中零 SQL 零 ORM 开销）；`_invalidate_user_cache`:78 统一失效点 + 
  `_schedule_post_commit_invalidation`:100（after_commit 二次失效，修「失效早于
  提交」窗口）；`_set_must_change_password` 补失效（原不失效，改密后旧标记残留
  一个 TTL 会让用户改完密码仍被门禁拒绝）。
- `role_service.py`:143,203：角色权限变更/分配后失效快照（`is_admin` 降级残留
  无黑名单兜底，只能靠失效）。
- 快照三个调用方：HTTP 认证链（`core/auth/dependencies.py`:92）、WS 认证
  （`core/auth/ws_auth.py`:59）、API key 校验（`agent_api/services/api_key_service.py`:127）。
- 新测试 `tests/features/user/test_auth_status_cache.py`（7 用例）：命中零 SQL
  断言、**提交后二次失效清脏回填**（用真实 AsyncSession 验证了 after_commit
  同步事件可取到事件循环并调度异步删除）、角色分配失效、改密标记失效、Redis
  故障降级、软删不缓存、回滚监听器语义。
- 回归：user + core + agent_api 268 passed；架构门禁 421 passed
  （SAVEPOINT AST 门禁、import 无环门禁均未受影响）。

## 设计决定及理由（防推翻重来）

1. **快照缓存 dict、不缓存 ORM 对象**。存量 `user:id` ORM 缓存命中路径
   （`user_repository.get_user_by_id`:218-229）反而 3 条 SQL（db.get + refresh +
   role 懒加载），是负收益；快照纯 dict 绕开 identity map/refresh/懒加载全部
   三个坑。存量负收益缓存**未修**（见未完成清单）。
2. **失效双保险：立即删 + 提交后二次删**。repository 不提交事务（仓库约定），
   写入口的失效发生在 commit 之前，并发请求可在失效后、提交前 miss 并回填
   旧值；提交后的回填读到的都是新值，所以提交后再删一次即可清掉窗口内脏回填。
3. **TTL 60s 是权限语义的显式取舍**（用户已知情？见「待确认」）：正常路径
   立即生效（失效即时 + 提交后二次失效），60s 只是「Redis 失效调用失败」时
   的脏读上限，与存量 RBAC 缓存 5min 宽容度同向。
4. **同会话先改后读会回填陈旧 role_code**（autoflush=False 下不能用
   `populate_existing` 修——它会抹掉同会话未 flush 的修改，失败方向不安全），
   已在 `get_auth_status_cached` docstring 写明调用前提；三个调用方均为请求
   开头只读，满足前提。**新调用方必须核查此前提**。
5. **jti 撤销黑名单保持实时 fail-close，不缓存**（登出必须立即生效）；
   禁用/软删用户有 `blacklist_all_user_tokens` 实时兜底。

## 需要用户知情/决策的事项

1. **[已实施，需知情]** 认证快照 60s 延迟窗口：API key 认证路径
   （api_key_service）不走 JWT 黑名单，禁用用户的 key 在「Redis 失效调用
   失败」的极端情况下最长 60s 仍可用；JWT 路径有黑名单兜底无此窗口。
2. **[未做，需拍板后才做]** 批次 3 成员 Redis 缓存：「成员被移除后最长 60s
   仍可访问」的取舍未获确认；contextvar 请求级去重（零语义变化）可以先行。
3. **[流程]** 两个提交落在本地 main 堆顶，与既有 23 个未推送提交同模式
   （本仓库工作流即「攒批后统一审查推送」），未推送。
4. **[基础设施]** `shared/cache` 死框架（CacheService/cached/CacheKeyBuilder/
   default_cache，全仓零外部调用）删 vs 复活未决策；批次 3-5 新缓存若不先
   决策此项，会继续散着手写键。

## 未完成清单（按优先级）

- **批次 2 残留**：jti EXISTS + 用户黑名单 GET 合并为一次 pipeline
  （`core/auth/dependencies.py:84-88`、`ws_auth.py:51-55`、`blacklist.py`），
  每请求省一次 Redis RTT。
- **批次 3**：成员/KB contextvar 请求级去重（零风险先行）+ Redis 缓存
  （member TTL 60s / kb TTL 10min，失效清单在盘点文档）。
- **批次 4**：预签名缓存（放 `minio_client.get_file_url` 层，三调用点自动
  受益；键 `presign:{bucket}:{object}`，TTL=expires-600s；附带修复浏览器
  HTTP 缓存永不命中的问题）；embedding 短 TTL 缓存（**键必须含模型名**）；
  查询改写缓存（`search_service.py:719` 的绕过改为缓存改写结果）。
- **批次 5**：页面级短 TTL（KB 六桶/会话中心/未读数/看板/wiki 统计，纯 TTL
  不做主动失效，唯一例外 mark_all_read 后删未读数键）；ES `ensure_index_exists`
  进程内 set 缓存（`elasticsearch_client.py:184`，写失败 index_not_found 时
  移出缓存重试）。
- **死代码**：删 `shared/cache` 的 CacheService/cached/get_cache_service/
  CacheKeyBuilder/default_cache 与 `redis_client.py` 向量缓存段（零外部调用，
  grep 已验证）；或反转决策为复活。
- **验收缺口（对应用户目标「检查缓存是否有效」）**：
  - 真机验证：起后端（8100）+ 真实 Redis/MySQL，登录取 token 连打两次
    同接口，对比 SQL 日志条数验证快照命中；改密/禁用后立即请求验证失效。
  - 命中率观测：快照读写已有 debug 日志（「认证快照命中」），可 grep 统计。
  - after_commit 二次失效仅在 aiosqlite 验证过；MySQL 驱动下未实测
    （SQLAlchemy 事件在 ORM 层与驱动无关，理论安全，但未实测）。
- **存量未修（本次顺带发现）**：存量 `user:id` ORM 缓存负收益路径
  （`get_user_by_id` 命中后 refresh + role 懒加载 3 条 SQL）；`soft_delete`
  以改名后的 username 调失效，`user:name:{旧名}` 键残留至 TTL（行为安全，
  仅孤儿键）。

## 本次实证的坑（接手必读）

1. **Windows 下 `Path.read_text/write_text` 会把 LF 翻成 CRLF** 造成整文件
   diff（本次 role_service.py 6 行改动变 416 行 diff，已用字节级替换修复并
   amend）。改行尾敏感文件一律 bytes 读写。
2. SQLite 下 BigInteger 主键不自增，tmp_db 建数据须显式给 id（先例
   `test_rbac_models.py`）。
3. rollback 会 expire ORM 属性，之后访问属性在 AsyncSession 下触发同步懒加载
   报 MissingGreenlet；测试需提前求值 id。
4. 测试注 Redis 假客户端的口子：`ClientFactory._instances["redis"]`（单例
   缓存先查后建，塞入即全局生效，teardown 还原）。
5. `create_from_credentials` 是同步回调——模型客户端构造链路唯一挂起点是
   凭证查询，并发时序测试一律挂那里。
6. `before_cursor_execute` 事件回调 6 参数（含 conn）。
7. pytest 无 pytest-timeout 插件，`--timeout` 参数不可用。

## 接手快速开始

```bash
cd backend
# 跑两批次测试
.venv/Scripts/python -m pytest tests/features/user/test_model_client_cache_locks.py tests/features/user/test_auth_status_cache.py -q
# 全量回归（本次基线：user+core+agent_api 268 绿 / 架构门禁 421 绿）
.venv/Scripts/python -m pytest tests/features/user/ tests/core/ tests/features/agent_api/ -q
```

批次 3 起步建议：先做 knowledge_space dependencies 的 contextvar 去重
（`features/knowledge_space/api/dependencies.py` 已有 `_request_user_cache`
先例可照抄），成员 Redis 缓存等用户对 60s 取舍拍板后再动。
