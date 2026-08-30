# 权限体系架构说明

> 权威参考：本文档描述系统权限机制的设计与边界。代码改动涉及权限时，同步更新本文。

## 三层总览

```
┌─ 认证层：你是谁            → JWT 双 token（core/auth）
├─ 平台管理面：谁能管平台    → RBAC 权限码（core/authorization + features/user）
├─ 空间资源面：谁能动资源    → 空间成员角色（features/knowledge_space）
└─ 对外集成：程序/外部身份   → 暂无（API Key / OIDC 未实现，见「对外集成现状」）
```

三层各管一件事，**不互相替代**：认证层回答"这是哪个用户"，管理面回答"这个用户能不能做平台管理操作"，资源面回答"这个用户能对这个空间里的资源做什么"。

## 认证层（core/auth）

- 双 token：access（30 分钟）+ refresh（7 天，轮换式，轮换后旧 refresh 立即失效）
- 双层黑名单：token 级（jti，登出/轮换写）+ 用户级（`user_blacklist:{uid}` 与 iat 比较，停用/删除/改密全量拉黑）
- 每个请求经 `get_current_user` 七步链：解码 → jti 黑名单 → 用户级黑名单 → 端口取 DB 状态 → 删除/禁用检查 → 强制改密门禁 → 返回用户 dict
- 端口解耦：core/auth 经 `UserStatusResolver` 端口取用户状态，不反向依赖 user feature（单向依赖门禁测试强制）
- 强制改密：`must_change_password=True` 的用户除豁免路径（改密/登出/me）外一律 403 `PASSWORD_CHANGE_REQUIRED`

## 平台管理面 RBAC（features/user）

**数据模型**：`User.role_id → Role ←(role_permissions)→ Permission`

**权限码是封闭枚举**（`core/authorization/permission_codes.py::SystemPermission`），只有 5 个，管理员只能组合到角色、不能新增：

| 权限码 | 用途 |
|---|---|
| `user.manage` | 用户管理（增删改、停用、重置密码、强制下线） |
| `role.manage` | 角色管理（角色 CRUD、权限配置、分配角色） |
| `skill.review` / `skill.config` | 技能审核 / 技能配置 |
| `agent.manage_system` | 系统级 Agent 管理 |

**预置角色**（startup `_init_rbac_seed` 幂等种子）：`admin`（全部权限）、`editor`（仅 agent.manage_system）、`viewer`（无，自注册默认）。

**查询实现**：`features/user/services/permission_service.py::RbacPermissionService`（实现 `PermissionCheckerPort`），Redis 缓存 `rbac:user_perms:{uid}` TTL 5 分钟（空集不缓存）。admin 角色**短路返回全部权限码**；`require_permission` 依赖里 `role_code == 'admin'` 再短路一次（不查表）。

**缓存失效**：分配角色（`assign_user_role`）、改角色权限（`update_role`）后主动 `invalidate`。

**覆盖范围**：user / role / skill 三个 feature 的管理端点。qa、agent、app、deep_research、evaluation、notification、clawmate 等业务 feature 的路由**只要求登录活跃**（`require_active_user`），无权限码差异——这是当前刻意的边界，业务面权限差异化属产品决策，未决策前不加码。

## 空间资源面（features/knowledge_space）

独立于 RBAC，查 `space_members` 表：

- `SpaceRole: VIEWER(0) < EDITOR(1) < ADMIN(2)`，空间 owner 天然 ADMIN
- 实现类：`services/permission_service.py::SpaceAccessChecker`
- 判断顺序：`custom_permissions` JSON（`resource → action → bool`，显式覆盖优先）→ 无覆盖回退角色层级
- 覆盖操作：空间/知识库/文档的增删改、成员邀请管理（如删除知识库需空间 ADMIN）
- 邀请机制：invite_token + 72 小时过期 + PENDING 状态流转

## 命名消歧（2026-08-30 收口）

历史上两个 feature 各有一个 `PermissionService` 类且语义完全不同，已改名消歧：

| 旧名 | 新名 | 位置 | 职责 |
|---|---|---|---|
| `PermissionService` | `RbacPermissionService` | `features/user/services/permission_service.py` | 系统权限码查询（Redis 缓存） |
| `PermissionService` | `SpaceAccessChecker` | `features/knowledge_space/services/permission_service.py` | 空间成员角色访问检查 |

**"admin" 双语义提醒**：系统 `admin` 角色 = 全局管理权限；空间 `SpaceRole.ADMIN` = 单空间管理员。二者互不相通，起名与排查问题时注意区分。

## 前端权限控制

- `stores/permission.ts`：登录后拉 `/users/me/permissions`；`hasPermission()` 对 `isAdmin` 短路全过
- 路由守卫 `meta.requiresAuth` / `meta.requiresPermission`
- UI 门禁 `v-if="permStore.hasPermission(...)"`（如 AppHeader 管理菜单）
- **前端权限码必须使用后端枚举里真实存在的码**（历史上出现过 `user.read`/`user.write`/`space.manage` 等幽灵码导致非 admin 有权用户被前端误拦，2026-08-30 已清理）

前端权限只是展示层优化，强制执行在后端依赖链。

## 对外集成现状

当前**没有任何对外集成机制**：无 OAuth/OIDC/LDAP/SSO，无 API Key/PAT，无服务间认证。外部系统接入的既定方向（未实现）：

1. **外部程序代表用户访问**（RPA/机器人/脚本）→ API Key 中间件换用户上下文后走现有权限链（复用 `encrypt_api_key_async` 加密存储）
2. **身份来自企业 IdP**（AD/钉钉/企微）→ OIDC 登录 + `external_identities` 映射表，映射不到按注册流程建 viewer
3. **NovaMind 调外部系统** → 已有：model_config 的 api_key 加密存储

在上述机制落地前，不要给外部系统共享用户密码。
