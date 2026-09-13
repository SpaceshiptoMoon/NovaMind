# 通知系统架构

> 2026-09-13 建成。骨架（表/服务/API/前端 UI）先行存在，本次补齐发送侧接线、
> WS 实时推送与跨 feature 端口。本文是通知系统的权威参考。

## 总览

```
[业务 feature]                        [notification feature]                 [前端]
skill / knowledge_space /             NotificationService                    stores/notification.ts
deep_research / app / user  ──Port──▶  ├─ 偏好过滤 (NotificationPreference)   ├─ WS 实时 prepend
                    NotificationPort   ├─ DB 落库 (notifications 表)  ◀──30s 轮询──┤ (兜底收敛)
                                       ├─ WS 推送 (ConnectionManager) ───────▶├─ 铃铛徽标 (AppHeader)
                                       └─ 邮件 (EmailService, 默认关)         └─ 通知中心页 (NotificationView)
```

设计原则：**DB 是事实源，WS 只是加速器**。推送失败静默，30s 轮询保证最终一致；
通知发送失败被 adapter 吞掉，绝不打断调用方主业务流程。

## 三层基础设施

### 1. NotificationPort（跨 feature 端口）

- `backend/src/shared/notification_ports.py`：`NotificationPort` Protocol，仅 `send` 一个方法
  （`user_id, type, title, content, link, extra_data`）。独立文件，对照 `model_config_ports.py` 先例。
- `backend/src/features/notification/adapters/notification_port_adapter.py`：`HostNotificationPort`
  实现 + `as_notification_port(db)` 工厂。**会话策略由调用点选择**：
  - HTTP 请求上下文：传 `db`（通知与主业务同事务，主业务回滚则通知一起回滚）
  - 后台任务/arq：传 `None`（每次 send 开独立短会话，调用方 session 可能已 commit/关闭）
- adapter 内部吞掉一切异常（记 warning 日志）；服务层 helper 建议再兜一层（双保险，
  见 `skill_marketplace_service._notify_review_result`）。

### 2. ConnectionManager（WS 连接注册表）

- `backend/src/core/ws/connection_manager.py`：per-user 连接集合（多标签页 = 多连接，推送全达），
  模块级单例 `manager`。
- **单进程架构前提**：arq worker 内嵌主进程，send 侧与持连侧同进程可达。
  将来 `--workers > 1` 时需在 `send_to_user` 后接 Redis pub/sub 跨进程广播（代码有注记）。
- 推送经 `dumps_event` 序列化（datetime 兜底）；单连接失败静默摘除，不影响其他连接。

### 3. WS 常驻订阅端点

- `POST` 面之外新增 `GET /api/v1/notifications/ws`（WebSocket），挂在现有 notifications router，
  manifest/router_manager 零改动。
- 认证：`Sec-WebSocket-Protocol: bearer.<jwt>` 子协议（`core/auth/ws_auth.py`），失败 accept 后
  close 4401/4403。
- 保活：客户端 25s 发 `{"action":"ping"}`，服务端回 `pong`；nginx `proxy_read_timeout 3600s`。
- 事件：`notification.new`，**data 为完整通知对象**（id/type/title/content/link/extra_data/
  is_read/created_at isoformat）——前端直接 prepend 不回源，规避「推送先到、commit 可见性后到」
  的读不到 race。

## 发送链路（send_notification 内部）

```
偏好过滤 (in_app_enabled + types_enabled 白名单，空=全收)
  → 落库 notifications
  → WS 推送（await 直调，send_to_user 内部吞错，无连接零开销）
  → 邮件（email_enabled 且 SMTP 已启用；失败仅 warning）
```

调用点铁律：**必须在业务 commit 之后调 port.send**——repo.create 只是 flush，
推送早于可见性会造成「推送了却随后回滚」的幽灵通知。

## 已接线事件（7 种 NotificationType 全部生效）

| type | 触发点 | 接收人 | link |
|---|---|---|---|
| skill_review | 后台审查三终态 + 异常转人工（`_do_review`）、管理员批准/拒绝 | 技能作者 | `/home/workspace/skills/{id}` |
| space_invite | `invite_member`（带完整 invite_token）、`add_member_direct` | 被邀请/被直加人 | `/home/spaces/{id}/join?token=` 或 `/home/spaces/{id}` |
| document_ready | 解析成功 / 用户取消 / 最终失败三终态（**重试中间态不发**） | 文档上传者 | `/home/spaces/{sid}/documents/{did}` |
| research_done | 深度研究流式 + 非流式两条路径 commit 后 | 发起用户 | `/home/workspace/research/{sid}/history` |
| resume_completed | 简历成功 / 最终失败 / 前置取消 | 发起用户 | `/home/apps/resume/session/{id}` 或 `/home/apps/resume/history` |
| password_reset | `forgot_password`（link=None，防枚举语义不变） | 请求重置者 | — |
| system | 预留 | — | — |

新增事件的步骤：调 `as_notification_port(...).send(...)` 即可，link 对照
`frontend/src/router/index.ts` 实际路由；测试 stub port 断言参数。

## 前端

- `api/notification.ts`：常驻 WS 客户端（`connectNotificationWs` / `disconnectNotificationWs`）。
  指数退避重连 1s→30s；close 4401/4403 **不重连**（token 无效/账号禁用，等轮询兜底或重新登录）；
  25s 心跳连续 2 次无 pong 主动断开触发重连；`window online` 立即重连；
  `TOKEN_SYNC_EVENT` 联动（登出断开、登录重连）。WS URL 拼接复用 `api/index.ts` 的 `createWsUrl`。
- `stores/notification.ts`：单一事实源。`items`（≤20 条，header 下拉）、`unreadCount`、`connected`。
  `init()`（幂等，登录后触发）= 拉基线 + 建 WS + 30s 轮询 unread-count 兜底；WS `onopen` 补拉收敛
  断线窗口；`stop()`（登出）全量清理。AppHeader 以 `watch(isLoggedIn)` 驱动 init/stop。
- 通知中心页（`views/user/NotificationView.vue`）含偏好设置区（站内/邮件开关 + 类型多选，
  经 `GET/PUT /notifications/preferences`）。

## 测试

- `backend/tests/core/test_ws_connection_manager.py`：注册表生命周期/多连接/异常摘除/datetime 兜底
- `backend/tests/features/notification/`：端口协议、send 落库+推送流程、WS 端点（ping/pong、4401、多标签页）
- 各 feature 下 `test_*_notification.py`：stub port 断言调用参数与时机
- 前端 `stores/__tests__/notification.test.ts`：init 幂等/WS 事件去重/截断/重连补拉/markRead/stop

## 明确不做 / 演进路径

- 多 worker：Redis pub/sub 广播（单进程不需要，注释留位）
- 通知删除端点：repository `delete_by_id` 已有，前端无交互，按需暴露
- SMTP 默认关闭（`smtp.enabled: false`），邮件通道已存在
