# 事务边界规范（后端）

> 2026-07-17 知识库模块审计后沉淀。澄清 CLAUDE.md「Repository 中写操作必须使用 `begin_nested()` (SAVEPOINT)，不要直接 commit」的落地解读，避免误读为「每个 repo 写方法都包 SAVEPOINT」而做高风险全量改动。

## 规则本意

CLAUDE.md 两条相关规则合在一起的本意：

- **Repository** 只做持久化查询/刷写（`flush` / `execute`），**不擅自提交**（不 `commit`）。
- **Service** 是事务编排者：控制事务边界（`commit` 时机），需要多步写原子性时用 `begin_nested()`（SAVEPOINT）包裹。

即：**提交由 Service 控制；SAVEPOINT 归属 Service 层的多步原子写，而非每个 repo 单步写。**

## 落地解读

### Repository 层
- 写方法用 `flush()`（让对象进入 session、拿到主键等）或 `execute(update/delete)`，**不 `commit`**。
- 单步写**不必**自己包 `begin_nested()`——无外层事务时 `begin_nested` 会隐式开外层事务，异常路径语义变化，徒增往返；且 Service 已在多步写处包了 SAVEPOINT 时再嵌套是无收益的嵌套。
- 当前知识库模块所有 repo 写方法均为 flush-only、零 commit，**符合规范**。

### Service 层
- `commit()` 是事务边界的确认点，**保留**。尤其当存在不可逆外部副作用时：
  - `delete_space` / `create_space` / `update_config` / 文档上传删除等：`commit` 在前、ES/MinIO 外部副作用在后。**移除 commit 会导致 DB 回滚但 ES/MinIO 数据已丢的不可逆不一致。**
- 多步写需要原子性时，用 `async with self.session.begin_nested():` 包裹。已有好例子：
  - `space_service.create_space`（建空间 + 加 owner 成员）
  - `space_service.delete_space`（级联软删 space/kb/doc/member/audit）
  - `document_service` 文档上传（create doc + MinIO upload）
- 不要在路由层 `commit()`（违反「业务逻辑在 service」分层）。已修：`document_routes` 的批次概览端点原在路由层 `db.commit()`，已上提为 `DocumentService.list_batch_overview`。

### 例外（刻意设计，勿动）
- `audit_service.log_action` 用**独立 session**（`get_db_session()`）+ 立即 `commit`：审计日志需在主事务回滚时仍留痕。这是有意行为，有注释自证。
  - 注意：独立 session + 「先审计后业务」的顺序会放大成伪审计（业务失败仍记为成功）。故审计调用应在**业务成功之后**（见 S5 修复）。

## 已知待跟踪项（不在本规范修复范围）
- `document_service` 部分后台任务路径用参数 `session` 而非 `self.session` 调用 `commit()`，需确认这些 session 与请求主事务的隔离关系，避免后台任务误提交主请求事务。单独立项核查。

## 检查清单（新增/改动写路径时）
- [ ] repo 写方法只 flush/execute，不 commit
- [ ] commit 由 service 控制，不在路由层
- [ ] 多步原子写用 `begin_nested` 包裹（service 层）
- [ ] 有 ES/MinIO 等外部副作用时，commit 在副作用之前
- [ ] 审计调用在业务成功之后（避免伪审计）