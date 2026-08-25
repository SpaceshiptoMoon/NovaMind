# 系统级 RBAC 鉴权设计

> 状态：设计已与用户确认，待 spec review 后进入实施计划
> 日期：2026-08-26
> 范围：backend 系统级 RBAC + 前端权限层；`knowledge_space` 域资源级 RBAC 保持现状

## 1. 背景与目标

### 1.1 现状（基于 2026-08-26 全局鉴权审计）

- **认证层完整**：JWT（`core/auth/token.py`）+ argon2 哈希（`core/auth/hashing.py`）+ Redis 双层黑名单（token 级 jti + 用户级 iat，`core/auth/blacklist.py` + `features/user/services/auth_service.py`）+ `UserStatusResolver` 端口装配（`features/user/adapters/auth_user_resolver_adapter.py`）。
- **系统级授权只有 `is_admin` 二值**：`User.is_admin` 列 + `core/auth/dependencies.py` `require_admin` 依赖。所有"管理员功能"（用户管理、skill 审核、系统级预置资源管理）全堆在 `is_admin` 上，无中间角色。
- **资源级 RBAC 仅 `knowledge_space` 域存在**：`SpaceMember`（role: VIEWER=0/EDITOR=1/ADMIN=2）+ `PermissionService`（`can_upload_document`/`can_delete_document`/`can_invite_member`/`can_manage_members` 等）+ `validate_space_admin/editor/member` 依赖 + `custom_permissions` 覆盖位。系统 admin 自动放行所有 space（`knowledge_space/api/dependencies.py:195-246` `validate_space_access`）。
- **非 space 域无成员/角色体系**：Agent/Skill/App/QA/Notification 只有单 `user_id` 属主模型，无法多人协作 + 角色分级。
- **前端 UI 权限与后端脱节**：前端只知 `is_admin`，不知用户在空间的 SpaceRole；无 `v-permission` 指令、无 permission store；成员管理按钮对 viewer 也显示（靠后端 403 兜底）；`requiresAdmin` meta 仅覆盖 2 个路由。
- **无高危漏鉴权/IDOR**：2026-07 的 IDOR 三端点（document process/cancel/retry）已修复；本次审计仅发现 1 个低危漏鉴权（`POST /skills/validate` 无 Depends，纯解析可被匿名 DoS）。

### 1.2 缺口（审计 §8）

1. 系统级只有 `is_admin` 二值，无中间角色。
2. 鉴权依赖散落、无强制收敛——`validate_space_*`/`_check_task_owner`/归属校验全靠路由逐端点手配，漏配即静默开放（evaluation `test_set` delete/update 无 creator 校验靠路由 `get_test_set_by_kb` 兜底即此模式）。
3. 非 space 域无成员/角色体系。
4. 无贯穿 tenant context（本次不做）。
5. 前端 UI 权限与后端 RBAC 脱节。
6. `custom_permissions` 字段保留但 UI/路由层未用（本次不做）。

### 1.3 目标

- **系统级 RBAC**：用角色 × 权限矩阵替代 `is_admin` 二值，支持可自定义角色，细粒度控制系统功能权限。
- **前端权限层**：permission store + `v-permission` 指令 + `requiresPermission` 路由 meta，驱动按钮/菜单显隐，补齐 UI 权限缺口。
- **删 `is_admin` 列**，改为从 role 派生，干净替代（同步改 JWT payload/依赖/前端 localStorage）。
- **补门禁**：AST/单测扫描"写端点无认证依赖"，杜绝漏配（审计缺口 2）。

### 1.4 非目标（本次不做，留后续议题）

- 资源级 RBAC 通用化扩展（把 `SpaceMember`/`PermissionService` 下沉 `core/authorization` 让 Agent/Skill 等挂载成员体系）——见审计缺口 3。
- 非 space 域成员体系（Agent/Skill 协作共享）。
- 请求级 tenant context + 查询自动 owner_id 过滤（审计缺口 4）。
- `custom_permissions` 前端设置入口（审计缺口 6，space 域内部议题）。
- `POST /skills/validate` 漏鉴权修复（独立小修，不阻塞本设计，可先行）。

## 2. 已确认设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| RBAC 作用域 | 系统级 + 前端权限层；space 资源级保持现状 | 系统级 is_admin 是真实缺口，space 域已完善 |
| 角色模型 | 可自定义角色（role/permission/role_permission 三表） | 灵活，管理员可建任意角色分配权限 |
| 用户绑角色 | 单角色（`User.role_id`） | 与 space 域单角色风格一致，企业系统角色通常互斥 |
| is_admin 处理 | 删除列，从 role 派生（`role.code == 'admin'`） | 干净替代 |
| 系统/space 角色关系 | 独立；系统 admin 自动放行所有 space（保留 `validate_space_access` 现有逻辑） | 最小改动，保持现状 |

## 3. 数据模型

### 3.1 新增三表

```python
# features/user/models/role.py（新建）
class Role(BaseModel):
    __tablename__ = "roles"
    id: BigInteger PK
    code: String(50), unique, not null       # 如 "admin"/"editor"/"viewer"/自定义
    name: String(100), not null               # 显示名
    description: String(255), nullable
    is_system: Boolean, default False         # 预置角色不可删，权限可调
    created_at / updated_at（来自 BaseModel）

class Permission(BaseModel):
    __tablename__ = "permissions"
    id: BigInteger PK
    code: String(100), unique, not null      # 如 "user.manage"
    name: String(100), not null
    module: String(50), not null              # 如 "user"/"skill"/"agent"
    description: String(255), nullable
    # 权限项系统预定义（代码枚举填充），管理员只组合到角色，不可新增/删除

class RolePermission(BaseModel):
    __tablename__ = "role_permissions"
    role_id: BigInteger, FK roles.id, PK
    permission_id: BigInteger, FK permissions.id, PK
```

### 3.2 User 改动

- **删除** `is_admin` 列。
- **新增** `role_id: BigInteger, FK roles.id, nullable=False`（注册用户默认绑定 `viewer` 角色，见 §3.3 迁移）。
- `User.is_admin()` 方法改为派生：`return self.role.code == 'admin'`（若 `role` 懒加载，注意 N+1，见 §4.4 缓存）。

### 3.3 预置系统角色与权限（启动初始化，幂等）

`features/user/api/startup.py` 新增 `_init_rbac_seed()`，幂等创建：

- **角色**（`is_system=True`）：
  - `admin`：全部权限
  - `editor`：基础读写权限（无 user.manage/role.manage/skill.review）
  - `viewer`：只读基础权限
- **权限项**（见 §4 权限矩阵，代码枚举 `SystemPermission` 填充 `permissions` 表）
- **角色权限映射**：admin 全勾，editor/viewer 按 §4 草案勾选

### 3.4 数据迁移（启动幂等脚本）

`features/user/api/startup.py` 迁移钩子（在 `_init_rbac_seed` 之后）：
1. 确保 `roles`/`permissions`/`role_permissions` 表存在并预置数据就绪。
2. 对每个现有 `User`：
   - 原 `is_admin=True` → `role_id = admin.id`
   - 原 `is_admin=False` → `role_id = viewer.id`（默认）
3. 删除 `users.is_admin` 列（`_run_schema_migrations` 幂等 DROP COLUMN）。

> DB schema 无 Alembic（记忆 `db-schema-sync-no-alembic`），用 `core/database` 的 startup `_run_schema_migrations` 幂等补列/删列钩子。SQLite 测试建表用 `tables=[User, Role, Permission, RolePermission]` 定向建表（记忆 `backend-test-sqlite-create-all-gotcha`）。

## 4. 权限矩阵（系统功能权限枚举）

### 4.1 权限项定义

| code | name | module | 控制功能 | 现有 require_admin 端点映射 |
|---|---|---|---|---|
| `user.manage` | 用户管理 | user | 用户增删/停用/重置密码/强制登出 | user: `POST /users`、`GET /users`、`DELETE /users/{id}`、`PATCH /users/{id}/status`、`POST /users/{id}/logout-all`、`POST /users/{id}/reset-password` |
| `skill.review` | 技能审核 | skill | 审核 approve/reject + reviews 列表 | skill: `POST /skills/admin/reviews/{id}/approve\|reject`、`GET /skills/admin/reviews` |
| `skill.config` | 技能管理配置 | skill | admin settings/models | skill: `GET/PUT /skills/admin/settings`、`GET /skills/admin/models` |
| `agent.manage_system` | 系统级 Agent 管理 | agent | 系统级预置 agent/mcp server 增删改 | agent: update/delete 传 `is_admin` 校验系统级预置资源（`agent_service.py:117-143`、`mcp_server_service.py:181-195`） |
| `role.manage` | 角色管理 | user | 角色 CRUD + 权限分配 + 用户角色分配 | 新增角色管理端点（§7） |

> `space.create`：现状 `space_router.py` create 用 `get_current_user_id`（任何登录用户可建），本次**不收紧**，保持现状（非目标）。

### 4.2 预置角色权限分配

- **admin**：全部权限（`user.manage`/`skill.review`/`skill.config`/`agent.manage_system`/`role.manage`）
- **editor**：`agent.manage_system`（可管理系统级 agent，按需）、无 `user.manage`/`skill.review`/`skill.config`/`role.manage`
- **viewer**：无系统管理权限（仅基础业务操作，业务权限由 space 域 RBAC 控制）

> 预置角色 `is_system=True` 不可删；权限可调（管理员可在 admin 角色外新建自定义角色勾选任意权限组合）。具体 editor/viewer 权限组合在实施时按业务确认，spec 仅定框架。

### 4.3 权限项扩展约定

新增系统功能权限时：在代码枚举 `SystemPermission` 加项 → 启动 seed 填充 `permissions` 表 → 现有角色不自动获得新权限（需管理员显式勾选，admin 角色除外，admin 可定义为"持有全部权限"或显式全勾）。

## 5. 后端实现

### 5.1 core/authorization（新建横切层）

位置：`backend/src/core/authorization/`（横切基础设施，与 `core/auth/` 平行，不进 features）。

```
core/authorization/
  __init__.py            # 导出 require_permission, PermissionService
  permission_codes.py    # SystemPermission 枚举（权限项 code 常量）
  permission_service.py  # PermissionService: get_user_permissions(user_id) -> set[str]，带 Redis 缓存
  dependencies.py        # require_permission(code) FastAPI 依赖
```

> 不违反单向依赖铁律：`core/` 是横切层，可被 features 依赖；`PermissionService` 通过端口/依赖注入取 Role/Permission 数据（不直连 features ORM），或下沉到 `features/user/services/` 由 `core/authorization` 经端口调用。**实施时按铁律确认**：若 `PermissionService` 需查 Role/Permission 表（features/user ORM），则 `PermissionService` 实现归 `features/user/services/`，`core/authorization` 只定义抽象端口 + 依赖；装配在 `features/user/api/startup.py`。

### 5.2 require_permission 依赖

```python
# core/authorization/dependencies.py
def require_permission(code: str):
    async def _dep(current_user: dict = Depends(get_current_user)):
        permissions = await PermissionService.get_user_permissions(current_user["id"])
        if code not in permissions and current_user.get("role_code") != "admin":
            raise PermissionDeniedError(message=f"缺少权限: {code}")
        return current_user
    return _dep
```

- 系统 admin（`role_code == 'admin'`）自动放行所有权限（等价原 `require_admin`）。
- 权限缓存：`PermissionService.get_user_permissions` 用 Redis 缓存 user→permissions（TTL 同 access token 或短，如 5 分钟）；角色权限变更时清相关用户缓存。

### 5.3 现有 require_admin 改造

- `core/auth/dependencies.py` `require_admin` 改为：`role_code == 'admin'` 放行（保留为系统 admin 快捷依赖，用于"仅系统管理员"语义，如 `role.manage`）。
- 现有 `require_admin` 端点按 §4.1 映射改用 `require_permission("user.manage")` 等，实现细粒度。

### 5.4 get_current_user 改造

- `core/auth/dependencies.py` `get_current_user` 返回 dict 新增 `role_code` + `permissions`（或在 JWT payload 携带，见 §6）。
- `UserStatusResolver` 端口扩展返回 role_code；或 `get_current_user` 内额外查 role。

### 5.5 门禁（补审计缺口 2）

- 新增 `tests/test_unidirectional_dependency_gate.py` 风格的 AST 扫描，或独立 `tests/test_auth_coverage_gate.py`：扫描所有 feature routes 的写端点（POST/PUT/PATCH/DELETE），断言有 `Depends(require_*)` 或 `Depends(validate_*)` 或 `Depends(get_current_user*)`。
- 现有漏配端点（`POST /skills/validate`）在门禁启用前先补 `require_active_user` + 限流。

## 6. JWT 与 is_admin 迁移

### 6.1 JWT payload 改造

`features/user/services/auth_service.py` `create_access_token`/`create_token_pair`：
- `is_admin` 保留但改为派生：`is_admin = (role_code == 'admin')`
- 新增 `role_code` 字段
- **是否在 payload 携带 `permissions` 列表**：选项 A（携带，前端直接从 JWT 解码，无需额外接口，但 token 变大 + 权限变更需重签 token）；选项 B（JWT 只带 role_code，前端调 `/user/me/permissions` 拉取，权限变更实时）。**推荐 B**（权限实时，token 紧凑），前端 permission store 调接口拉。

### 6.2 is_admin 引用改造清单

| 位置 | 改造 |
|---|---|
| `features/user/models/user.py` | 删 `is_admin` 列；`is_admin()` 方法改派生 `self.role.code == 'admin'`；加 `role_id` + `role` relationship |
| `core/auth/dependencies.py` `get_current_user` | dict 加 `role_code`；`is_admin` 从 role_code 派生 |
| `core/auth/dependencies.py` `require_admin` | 基于 `role_code == 'admin'` |
| `features/user/services/auth_service.py` `create_access_token` | payload `is_admin` 从 role 派生 + 加 `role_code` |
| `features/user/services/user_service.py` `create_user`/`register_user` | `is_admin` 参数改为 `role_id`/`role_code`（注册强制 `viewer`） |
| `features/agent/services/agent_service.py`/`mcp_server_service.py` | `_is_admin(current_user)` 改读 `current_user["role_code"] == 'admin'` 或 `current_user["is_admin"]`（派生值仍可用） |
| `frontend/src/stores/user.ts` `isAdmin` | 改为 `hasPermission('role.manage')` 或读 `role_code == 'admin'`（从接口/profile） |
| `frontend/src/router/guards.ts` `requiresAdmin` | 读 `user.role_code == 'admin'` 或 `hasPermission` |
| `frontend` 各 `userStore.isAdmin`/`user.is_admin` UI | 改 `hasPermission`/`role_code` |

### 6.3 兼容性

- 过渡期 JWT payload 同时带 `is_admin`（派生）+ `role_code`，旧 token 刷新后自然升级；登出/黑名单机制不变。
- 前端 `localStorage.user.is_admin` 改为从 profile 接口派生（`role_code == 'admin'`），或弃用 `is_admin` 字段改用 `role_code` + `permissions`。

## 7. 角色管理 CRUD + UI

### 7.1 后端端点（`features/user/api/role_routes.py` 新建，prefix `/api/v1/user`）

全部 `require_permission('role.manage')`：

| 端点 | 功能 |
|---|---|
| `GET /roles` | 角色列表（含 permissions） |
| `POST /roles` | 新建角色（code/name/description + permission_codes） |
| `PUT /roles/{id}` | 改角色（is_system 角色仅改 description/权限，不改 code） |
| `DELETE /roles/{id}` | 删角色（is_system 不可删；有用户绑定不可删或提示先迁移） |
| `GET /permissions` | 权限项列表（供前端勾选） |
| `PUT /users/{id}/role` | 分配用户角色（改 `user.role_id`，清该用户权限缓存） |

- `features/user/services/role_service.py`（新建）：Role CRUD + 权限分配 + 用户角色分配 + 权限缓存清理。
- `features/user/repository/role_repository.py`（新建）。
- `features/user/schemas/role_schema.py`（新建）：`RoleBase`/`RoleCreate`/`RoleUpdate`/`RoleResponse`/`PermissionResponse`，按 `*Base→*Create/*Update→*Response` 分层（`from_attributes=True`）。
- `features/user/manifest.py` 注册 `role_router`。
- `router_manager.py` 无需手动注册（manifest 自动聚合，但按项目规则新路由注册确认 manifest 已挂）。

### 7.2 前端 UI

- 新增 `frontend/src/views/admin/RoleManageView.vue`：角色列表、新建/编辑角色（勾选权限）、删除（is_system 禁用）、给用户分配角色入口。
- 路由 `/home/admin/roles`，`meta: { requiresPermission: 'role.manage' }`。
- `frontend/src/api/user.ts` 加角色管理 API；`frontend/src/api/types.ts` 加 `Role`/`Permission`/`RoleCreateRequest` 等类型。
- 用户管理页（`UserManageView.vue`）加"分配角色"操作（调 `PUT /users/{id}/role`）。

## 8. 前端权限层

### 8.1 permission store

- `frontend/src/stores/permission.ts`（新建）：登录后调 `/user/me/permissions` 拉取并缓存 `permissions: string[]` + `role_code: string`；`hasPermission(code): boolean`；`isAdmin` getter（`role_code === 'admin'`）。
- `frontend/src/api/user.ts` 加 `getMyPermissions(): Promise<{ permissions: string[]; role_code: string }>`。
- `useUserStore.login`/`register` 成功后触发 permission store 拉取；`logout` 清空。

### 8.2 v-permission 指令

- `frontend/src/directives/permission.ts`（新建）：`v-permission="'user.manage'"` 或 `v-permission="['user.manage', 'role.manage']"`（任一满足），无权限移除元素。
- `main.ts` 注册指令。
- `frontend/src/composables/usePermission.ts`（新建）：`hasPermission` composable 供 script 内判断。

### 8.3 路由守卫改造

- `frontend/src/router/guards.ts`：新增 `requiresPermission` meta 处理（无权限跳 `/403`）；`requiresAdmin` 保留为 `requiresPermission: 'role.manage'` 的等价或读 `role_code`。
- 现有 `requiresAdmin` 路由（`/home/admin/users`、`/home/workspace/skills/admin`）改用 `requiresPermission`；新增 `/home/admin/roles`。

### 8.4 现有 UI 改造（补审计缺口 5）

| 位置 | 改造 |
|---|---|
| `AppHeader.vue:49` 系统管理项 | `v-if="hasPermission('role.manage') \|\| hasPermission('user.manage')"` 等 |
| `SkillMarketplaceView.vue:4` 管理入口 | `v-permission="'skill.review'"` 或 `'skill.config'` |
| `UserManageView.vue:80/232` 删除按钮 | 保留 `hasPermission('user.manage')` |
| `SpaceSettingsView.vue:275` 成员管理按钮 | 改按当前用户在该空间的 SpaceRole 判断（需 permission store 扩展存当前用户在各 space 的 role，或调 `validate_space_admin` 等价接口）——**注**：此为 space 域 UI 权限，本设计主要做系统级，space 域 UI 权限作为附带改进（见 §10 议题） |

## 9. 测试与门禁

### 9.1 后端 pytest（`tests/test_rbac*.py` 新建）

- `require_permission` 放行/拒绝（有/无权限用户）。
- 系统 admin 自动放行所有权限。
- 权限缓存命中/角色变更清缓存。
- `is_admin` 派生正确（`role_code == 'admin'`）。
- 数据迁移幂等（`is_admin=True→admin`、`is_admin=False→viewer`、重复运行不重复建角色）。
- AST 门禁：写端点无认证依赖报错；`POST /skills/validate` 已补依赖后门禁通过。
- 角色管理 CRUD + 权限分配 + 用户角色分配（`require_permission('role.manage')` 守卫）。
- 现有 `require_admin` 端点改 `require_permission` 后行为等价。

### 9.2 前端

- `npm run type-check && npm run lint`：v-permission 指令、permission store、RoleManageView、路由 meta 类型。
- 手动：登录不同角色用户，验证按钮/菜单显隐 + 路由守卫 + 后端 403 兜底。

## 10. 附带议题（本设计范围外但相关，记为后续）

- **space 域 UI 权限**：前端存当前用户在各 space 的 SpaceRole，驱动 `SpaceSettingsView` 成员管理按钮等显隐（审计缺口 5 的 space 部分）。
- **资源级 RBAC 通用化**：`SpaceMember`/`PermissionService` 下沉 `core/authorization`，Agent/Skill 等挂载成员体系（审计缺口 3）。
- **tenant context**：contextvar 存 current_user/space_id，repository 查询自动注入 owner_id 过滤（审计缺口 4）。
- **`custom_permissions` 前端入口**（审计缺口 6）。

## 11. 文件清单（实施触点）

### 后端新增
- `features/user/models/role.py`（Role/Permission/RolePermission）
- `core/authorization/`（`__init__.py`/`permission_codes.py`/`permission_service.py`/`dependencies.py`）或 `features/user/services/permission_service.py` + core 端口
- `features/user/services/role_service.py`
- `features/user/repository/role_repository.py`
- `features/user/schemas/role_schema.py`
- `features/user/api/role_routes.py`
- `tests/test_rbac_*.py`、`tests/test_auth_coverage_gate.py`

### 后端改动
- `features/user/models/user.py`（删 is_admin 列、加 role_id、is_admin() 派生）
- `features/user/api/user_routes.py`（require_admin → require_permission）
- `features/user/api/startup.py`（seed 角色/权限 + 数据迁移 + 删列钩子）
- `features/user/services/user_service.py`（create_user/register_user 改 role）
- `features/user/services/auth_service.py`（JWT payload 加 role_code、is_admin 派生）
- `features/user/schemas/user_schema.py`（UserResponse 去 is_admin 或改派生、加 role）
- `core/auth/dependencies.py`（get_current_user 加 role_code、require_admin 改）
- `features/skill/api/routes.py`（`POST /skills/validate` 补依赖 + require_admin→require_permission）
- `features/user/manifest.py`（注册 role_router）
- `features/skill/api/routes.py`（admin 端点 require_permission）

### 前端新增
- `src/stores/permission.ts`
- `src/directives/permission.ts`
- `src/composables/usePermission.ts`
- `src/views/admin/RoleManageView.vue`
- `src/api` 角色管理函数 + 类型

### 前端改动
- `src/stores/user.ts`（login/register 触发权限拉取、isAdmin 改派生、logout 清权限）
- `src/router/guards.ts`（requiresPermission）
- `src/router/index.ts`（/home/admin/roles 路由、requiresAdmin→requiresPermission）
- `src/views/auth/LoginView.vue` 等（无）
- `src/components/AppHeader.vue`（系统管理项 v-permission）
- `src/views/skill/SkillMarketplaceView.vue`（管理入口 v-permission）
- `src/views/user/UserManageView.vue`（删除按钮 + 分配角色操作）
- `src/main.ts`（注册 v-permission 指令）
- `src/api/types.ts`（Role/Permission/角色管理类型）

## 12. 风险与回滚

- **删 `is_admin` 列破坏性**：迁移脚本必须幂等，先建 role/绑用户、再删列；保留迁移前备份/可回滚（删列前确认所有用户已绑 role_id）。
- **JWT 兼容**：payload 带 `is_admin`（派生）过渡，旧 token 仍可解；权限实时性靠 `/user/me/permissions` 接口。
- **权限缓存一致性**：角色权限变更/用户角色变更必须清缓存，否则权限残留。
- **门禁误报**：AST 门禁白名单（公开端点：login/register/refresh/forgot/reset/health/docs/skills-marketplace 等设计性公开），需维护白名单。
- **单向依赖铁律**：`core/authorization` 若需查 Role/Permission 表，经端口注入，不直连 features ORM；`PermissionService` 实现可归 `features/user/services/`，core 只定义抽象。实施时以 `tests/test_unidirectional_dependency_gate.py` 验证。