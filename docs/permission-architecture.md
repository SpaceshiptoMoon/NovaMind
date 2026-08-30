# 权限体系架构说明

> 权威参考：本文档描述系统权限机制的设计与边界。代码改动涉及权限时，同步更新本文。
> 2026-08-30 按三级全局模型定稿重写（原三层调研版已被取代）。

## 总览

```
┌─ 认证层：你是谁              → JWT 双 token（core/auth）
├─ 全局层：你在平台是什么身份  → 三级：超管 / 授权管理员 / 普通用户（features/user）
├─ 应用层：哪些应用对你开放    → deny-list 门禁（user_disabled_apps + AppGateMiddleware）
├─ 空间资源面：你能动什么资源  → 空间成员角色（features/knowledge_space）
└─ 对外集成：程序/外部身份     → 暂无（API Key / OIDC 未实现）
```

各层只回答一个问题，不互相替代。一次请求的完整执行顺序：

```
认证（get_current_user / ws_authenticate）
  → 应用门禁（AppGateMiddleware：被禁应用的 HTTP/WS 直接 403/4403）
    → 平台权限码（require_permission：管理端点）
      → 空间角色（SpaceAccessChecker：空间资源操作）
```

## 认证层（core/auth）

- 双 token：access（30 分钟）+ refresh（7 天，轮换式，轮换后旧 refresh 立即失效）
- 双层黑名单：token 级（jti，登出/轮换写）+ 用户级（`user_blacklist:{uid}` 与 iat 比较，停用/删除/改密全量拉黑）
- 每个请求经 `get_current_user` 七步链：解码 → jti 黑名单 → 用户级黑名单 → 端口取 DB 状态 → 删除/禁用检查 → 强制改密门禁 → 返回用户 dict
- WS 认证等价：subprotocol `bearer.<jwt>`（`core/auth/ws_auth.py`），失败 close 4401/4403

## 全局层：三级身份（features/user）

| 身份 | 载体 | 能做什么 |
|---|---|---|
| **超级管理员** | `users.is_super_admin = true`（YAML 配置的初始 admin 账号，startup 置位） | 一切；且不可被任何管理端点删除/停用/重置密码/改角色/强制下线（五处绝对保护，见 `UserService._ensure_not_super_admin` 等） |
| **授权管理员** | 被分配 `admin` 角色（`PUT /users/{id}/role`） | 平台全部管理操作 + 全部应用直通；可给其他用户授权/收回（含把别人提成管理员），但动不了超管 |
| **普通用户** | `viewer` 角色（注册默认） | 全部应用默认可用（可被管理员禁用具体应用）；空间操作看空间角色 |

要点：

- 超管与授权管理员的**唯一区别**是 `is_super_admin` 标记——授权管理员理论上可被另一管理员降级，超管不可。
- 超管角色只能通过改 YAML `admin` 配置变更，管理端点一律 403（`PermissionDeniedError`）。
- 权限码是封闭枚举（`core/authorization/permission_codes.py::SystemPermission`，5 个：user.manage / role.manage / skill.review / skill.config / agent.manage_system），admin 角色短路返回全部。
- **editor 角色已废弃**（2026-08-30）：三级模型下无位置，存量用户由 `_deprecate_editor_role` 迁移至 viewer 后删除。
- 查询实现：`RbacPermissionService`（Redis 缓存 `rbac:user_perms:{uid}` TTL 5 分钟）。

## 应用层：deny-list 门禁

**语义**：默认全开放，管理员可禁用普通用户的具体应用；应用相互隔离（禁 agent 不影响 qa）；未记录 = 可用。

**数据**：`user_disabled_apps(user_id, app_code, created_by)`，联合唯一 `(user_id, app_code)`。表通常接近空——新用户/存量用户零迁移天然全开。

**可门禁应用**（`core/authorization/app_codes.py::AppCode`）：

| 代码 | 应用 | 路由前缀 |
|---|---|---|
| `qa` | AI 对话 | /api/v1/qa、/api/v1/ai-chat、/api/v1/sessions |
| `agent` | 智能体 | /api/v1/agent |
| `skill` | 技能广场 | /api/v1/skills |
| `app` | 应用中心（简历挖掘） | /api/v1/apps |
| `clawmate` | ClawMate | /api/v1/clawmate |

**不进门禁**：知识空间（入口人人可见，内容由空间角色控制）、深研究/测评（空间功能）、通知/个人设置（人人可用）。新增 feature 或改挂载前缀时同步更新 `GATED_APP_PREFIXES`。

**执行点**：`core/middleware/app_gate.py::AppGateMiddleware`（纯 ASGI，app_factory 注册于 CORS 内层）：

- 按 `scope["type"]` 分流：http 取 `Authorization` 头，websocket 取 `sec-websocket-protocol` 的 `bearer.` 前缀——router 级依赖的 `HTTPBearer` 会拒绝 WS 握手，这是选纯 ASGI 的原因
- 段边界匹配（`/api/v1/agentx` 不误命中）；CORS 预检直通
- admin claims 直通；无 token/解码失败直通（端点认证自会 401/4401）
- 命中禁用：http 403 `{"code": "APP_ACCESS_DENIED"}`，WS 握手拒绝（close 4403）
- 检查异常 fail-open 放行 + error 日志（门禁是可见性控制，安全边界在端点认证与空间成员表）
- 服务层：`AppAccessService`（Redis 缓存 `appgate:disabled:{uid}` TTL 5 分钟，空集也缓存；全量替换走 SAVEPOINT）

**管理端点**：`GET/PUT /users/{id}/app-access`（`user.manage` 守卫，PUT 全量替换被禁集合）；前端在 `/users/me/permissions` 的 `disabled_apps` 一次拉全。

**安全语义**：admin 直通依据 JWT claims（≤30 分钟陈旧性——刚降级的管理员最长残留一个 access token 周期；撤销类检查不受影响，端点认证层仍强制）。这是产品可见性控制与安全边界的取舍，已注明。

## 空间资源面（features/knowledge_space）

独立于全局层与应用层，查 `space_members` 表：

- `SpaceRole: VIEWER(0) < EDITOR(1) < ADMIN(2)`，空间 owner 天然 ADMIN
- 实现类：`services/permission_service.py::SpaceAccessChecker`
- 判断顺序：`custom_permissions` JSON（`resource → action → bool`，显式覆盖优先）→ 无覆盖回退角色层级
- 邀请机制：invite_token + 72 小时过期 + PENDING 状态流转
- 被拉进空间并给予角色，才能操作该空间内容——「除非把我拉到对应空间」的执行点

## 命名消歧（2026-08-30 收口）

| 类名 | 位置 | 职责 |
|---|---|---|
| `RbacPermissionService` | `features/user/services/permission_service.py` | 平台权限码查询（Redis 缓存） |
| `SpaceAccessChecker` | `features/knowledge_space/services/permission_service.py` | 空间成员角色访问检查 |
| `AppAccessService` | `features/user/services/app_access_service.py` | 应用禁用查询/替换（deny-list） |

**"admin" 三语义提醒**：系统 `admin` 角色 / `users.is_super_admin` 超管标记 / 空间 `SpaceRole.ADMIN`，三者互不相通。

## 前端权限控制

- `stores/permission.ts`：登录后拉 `/users/me/permissions`（含 `disabled_apps`）；`hasPermission()` 与 `hasApp()` 都对 `isAdmin` 短路全过
- 路由守卫：`meta.requiresAuth` / `meta.requiresPermission` / `meta.requiresApp`（被禁应用 403）
- 导航过滤：工作台侧边栏频道、顶部「应用」导航、应用中心卡片按 `hasApp` 过滤；research 属空间功能常驻
- 用户管理页：「应用权限」勾选弹窗（勾=可用，提交转被禁集合）、「设为角色」弹窗；超管行打标签且危险操作按钮禁用
- 前端权限只是展示层优化，强制执行在后端依赖链与中间件

## 对外集成现状

当前**没有任何对外集成机制**：无 OAuth/OIDC/LDAP/SSO，无 API Key/PAT，无服务间认证。外部系统接入的既定方向（未实现）：

1. **外部程序代表用户访问**（RPA/机器人/脚本）→ API Key 中间件换用户上下文后走现有权限链（复用 `encrypt_api_key_async` 加密存储）
2. **身份来自企业 IdP**（AD/钉钉/企微）→ OIDC 登录 + `external_identities` 映射表，映射不到按注册流程建 viewer
3. **NovaMind 调外部系统** → 已有：model_config 的 api_key 加密存储

在上述机制落地前，不要给外部系统共享用户密码。

## 范围外（已决策未实施）

- **空间治理旁路**：系统管理员查看全部空间/转移所有权/回收——后续批次
- **检索/问答空间权限过滤加固**：独立安全任务
- **viewer → member 改名**：无功能价值，不做
