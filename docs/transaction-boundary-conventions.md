# 事务边界规范（后端）

> 2026-07-17 知识库模块审计后沉淀；**2026-10-03 修订**：落地解读已按现行代码实践更新。
> CLAUDE.md 规则「Repository 写操作必须使用 `begin_nested()` (SAVEPOINT)，不要直接 commit」的字面要求自 2026-09 起已成为全仓主流实践（notification/agent_api/qa/knowledge_ops/user/search_config/wiki 等新 repo 均为 `begin_nested + flush` 写法，多个 docstring 自证为硬规则）。本文初版「repo 单步写不必包 SAVEPOINT、flush-only」的解读描述的是 2026-07 时点的知识库存量代码，已被实践超越，仅作历史背景保留。

## 规则本意（现行版）

CLAUDE.md 规则拆成两条不变式：

- **Repository 绝不 `commit()`**——提交权永远在 Service（事务编排者）。
- **Repository 写操作包 `begin_nested()`（SAVEPOINT）**——单步写自带原子边界：步骤失败只回滚该 SAVEPOINT，调用方（如批量扇出的逐条 skip-and-continue）可继续后续步骤；SAVEPOINT 释放后变更仍挂在外层事务，随 Service 的 `commit()` 落库。

即：**提交由 Service 控制；repo 单步写以 SAVEPOINT 为原子单位，二者不冲突。**

## 落地解读

### Repository 层（现行约定）
- 写方法统一 `async with session.begin_nested():` 包裹 + `flush()`（拿到主键/时间戳可再 `refresh()`），**不 `commit()`**。标准样例：`agent_api/repository/api_key_repository.py`、`notification/repository/notification_repository.py`。
- 2026-07 存量的 flush-only 写法（knowledge_space 早期 repo）不要求全量改造——它们同样满足「零 commit」不变式，改动触及时顺手对齐即可。
- 已知刻意例外：`knowledge_space/repository/document_task_repository.py` 的批次概览路径保留 flush-only 并有注释自证（紧急路径，勿动）。

### Service 层
- `commit()` 是事务边界的确认点，**保留**。尤其当存在不可逆外部副作用时：
  - `delete_space` / `create_space` / `update_config` / 文档上传删除等：`commit` 在前、ES/MinIO 外部副作用在后。**移除 commit 会导致 DB 回滚但 ES/MinIO 数据已丢的不可逆不一致。**
- 多步写需要原子性时，用 `async with self.session.begin_nested():` 包裹。已有好例子：
  - `space_service.create_space`（建空间 + 加 owner 成员）
  - `space_service.delete_space`（级联软删 space/kb/doc/member/audit）
  - `document_upload_service` 文档上传（create doc + MinIO upload，见 `upload_document`）
- 不要在路由层 `commit()`（违反「业务逻辑在 service」分层）。已修：`document_routes` 的批次概览端点原在路由层 `db.commit()`，已上提为 `DocumentTaskService.list_batch_overview`。

### 例外（刻意设计，勿动）
- `audit_service.log_action` 用**独立 session**（`get_db_session()`）+ 立即 `commit`：审计日志需在主事务回滚时仍留痕。这是有意行为，有注释自证。
  - 注意：独立 session + 「先审计后业务」的顺序会放大成伪审计（业务失败仍记为成功）。故审计调用应在**业务成功之后**（见 S5 修复）。

## 已知待跟踪项（不在本规范修复范围）
- `document_pipeline` 部分后台任务路径用参数 `session` 而非 `self.session` 调用 `commit()`，需确认这些 session 与请求主事务的隔离关系，避免后台任务误提交主请求事务。单独立项核查。

> 批次 2 已核查（2026-07）：**隔离安全**。文档处理后台入口 `features/knowledge_space/tasks/document_tasks.py`
> 的 `process_document_task` 用 `async with get_db_session() as session:` 创建**全新后台 session**，
> 再透传给管道 helper（`persist_parsed_text` / `run_post_parse_tail` 等，现位于
> `services/pipeline_steps.py`；`execute_document_pipeline` / `_process_image_document_static`
> 在 `document_pipeline.py`）提交。这些 helper 提交的是后台独立 session，
> 不接触任何请求主事务。`_cancel_batch_enqueue`（现位于 `document_task_service.py`）同样用 `get_db_session()` 独立 session。
> 结论：helper「commit 参数 session」是正确行为（后台任务自带 session），无需修复。
> 抽库相关不变式已补：`RetrievalEngine` 绝不持有 session / 绝不 commit（仅 es_client + logger + cache）。

## 检查清单（新增/改动写路径时）
- [ ] repo 写方法包 `begin_nested` + `flush`，绝不 `commit`
- [ ] commit 由 service 控制，不在路由层
- [ ] service 多步原子写可用 `begin_nested` 包裹（与 repo 层 SAVEPOINT 嵌套无冲突）
- [ ] 有 ES/MinIO 等外部副作用时，commit 在副作用之前
- [ ] 审计调用在业务成功之后（避免伪审计）