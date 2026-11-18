# 单进程边界规范（后端）

> 2026-11-15 架构收敛批次沉淀。起因：进程内全局状态盘点发现 15+ 处单例/进程级表，
> 均按「单 worker 进程」假设设计且无文档声明——部署者执行 `--workers 2` 会得到
> 静默故障（无报错、功能漂移），本文将该边界显式化。

## 规则本意

- **本服务按单 worker 进程设计。** 部署入口（`main.py --workers`、supervisord、
  compose）默认并应保持 1 个 worker 进程；水平扩展不在当前架构支持范围内。
- **单进程不是缺陷而是取舍**：嵌入式任务 worker（API 进程兼任 arq consumer）、
  进程内 WS 路由、内存审批路由表，三者共同构成零外部依赖的部署形态
  （DB/Redis/ES/MinIO 之外无协调组件）。
- **机器化执行**：启动期运行形态诊断（`app_factory._diagnose_runtime_shape`）检测
  `--workers > 1` 打 WARNING（只告警不阻断，与 `SecurityConfigValidator` 同款模式）。

## 进程内状态清单（多 worker 下的故障形态）

| 持有点 | 位置 | 多 worker 下的故障 |
|---|---|---|
| `ConnectionManager()` | `core/ws/connection_manager.py:89` | WS 连接表按进程分片：HTTP/arq 侧 `send_notification` 路由不到其他进程的连接，通知静默丢失 |
| `model_config_service._key_locks` | `features/user/services/model_config_service.py:73` | 模型客户端 per-key 锁失去互斥语义，跨进程并发构造重复客户端 |
| `PromptManager._templates`（类级） | `shared/prompts/prompt_manager.py:15` | 模板表每进程一份（只读，无损） |
| `ClientFactory._instances`（类级） | `shared/storage/client_factory.py:28` | 客户端单例每进程一份（无损，但失效广播只达本进程） |
| 嵌入式 arq worker（`_worker_task`） | `shared/mq/worker.py:14` | **每个 API 进程都起任务 consumer**：同一任务被多进程争抢，cron 任务重复执行 |
| `_asr_executor`（ProcessPoolExecutor 1 worker） | `engines/document/media/audio/audio_utils.py:246` | ASR 串行化租约失效：多进程各持 executor，GPU/CPU 过载 |
| `asr_lease._holder_token` | `engines/document/media/audio/asr_lease.py:35` | Redis 租约失败时的进程内退化语义跨进程失效 |
| `_limiter`（slowapi 内存计数器） | `core/middleware/rate_limit.py:65` | 限流阈值按进程分片，实际放行量 = 配置 × N |
| `_engine`/`_session_factory` | `core/database/database.py:14` | 每进程独立连接池（正常，注意总连接数 = pool × workers） |
| `_arq_pool` | `shared/mq/__init__.py:11` | 每进程独立连接池（同上） |
| `_config`/`_config_dict` | `setting/yaml_config/loader.py:429` | 配置缓存每进程一份（无损） |
| `_default_encryption_key` | `shared/utils/crypto.py:19` | 启动注入每进程执行（同源无损） |

**判读口径**：标注「无损」的项只是内存重复；标注「故障」的项在多 worker 下产生
用户可感知的静默错误（通知丢失/审批超时/任务重复执行/限流失效），是禁止多 worker
的根因。

## 水平扩展演进路径（仅声明，未排期）

真要多 worker 时按依赖顺序补两件事，缺一不可：

1. **WS 跨进程广播**：ConnectionManager 的进程内表换成 Redis pub/sub fan-out
   （前端协议不变，服务端 `send_notification` 改经 Redis 频道广播到各进程本地投递）。
2. **任务 worker 拆分**：嵌入式 arq consumer 关闭（`--workers > 1` 时禁用），
   任务消费交给独立 worker 进程（arq 原生多进程安全，依赖 Redis 锁）。

（原第 2 项「审批路由外置：`DETACHED_APPROVAL_ROUTES` 决策回传改经 Redis」已随
2026-11-15 agent 模块剥离作废——该符号现全仓不存在。）

完成后仍需审计上表「无损」项的失效广播语义（ClientFactory 缓存失效目前是进程内
事件，跨进程需要 pub/sub 通道）。

## 例外与现状

- 开发热重载（`--reload`）：单进程语义不受影响（main.py 强制 workers=1）。
- 嵌入式 arq worker 与 API 同进程是**核心单进程假设**：拆分它即破坏「一条命令
  起全栈」的部署形态，属架构级变更需先立计划。
