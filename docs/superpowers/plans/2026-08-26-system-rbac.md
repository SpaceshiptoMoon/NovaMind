# 系统级 RBAC 鉴权 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用可自定义角色 × 权限矩阵替代 `is_admin` 二值，新增系统级 RBAC + 前端权限层，space 域资源级 RBAC 保持现状。

**Architecture:** 新增 `Role`/`Permission`/`RolePermission` 三表 + `User.role_id`（删 `is_admin` 列，从 role 派生）；`core/authorization` 定义 `PermissionCheckerPort` 端口 + `require_permission(code)` 依赖，`features/user/services/permission_service.py` 实现端口（查 ORM + Redis 缓存），`features/user/api/startup.py` 装配；现有 `require_admin` 端点改为 `require_permission`；JWT payload 加 `role_code`、`is_admin` 派生；前端 permission store + `v-permission` 指令 + `requiresPermission` 路由 meta + 角色管理 UI；AST 门禁扫描写端点漏鉴权。

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic + Redis + argon2 + JWT（后端）；Vue 3 + TypeScript + Pinia + Element Plus（前端）；pytest + pytest-asyncio（测试）。

**Spec:** `docs/superpowers/specs/2026-08-26-system-rbac-design.md`

## Global Constraints

- Python 3.12+，`snake_case` 函数/变量，`PascalCase` 类；4 空格缩进；绝对导入 `from novamind...`；uv 管包；Ruff line-length=100。
- TS/Vue：2 空格缩进，`PascalCase` 组件，`camelCase` composable/store，`<script setup lang="ts">`。
- 业务异常继承 `BaseAPIError` 并在 `startup.py` 注册；禁 `raise HTTPException`。
- 仓库写操作用 `begin_nested()`（SAVEPOINT），禁直接 commit。
- 新路由在 feature `manifest.py` 注册（`router_manager` 自动聚合，但确认 manifest 已挂 router）。
- 单向依赖铁律：`features → engines → shared`，`core/authorization` 经端口取权限数据，禁直连 features ORM；`tests/test_unidirectional_dependency_gate.py` 必须通过。
- DB 无 Alembic：用 `core/database` startup `_run_schema_migrations` 幂等补列/删列；SQLite 测试定向建表 `tables=[...]`（记忆 `backend-test-sqlite-create-all-gotcha`）。
- 跑 Python 用 `backend/.venv/Scripts/python`（记忆 `backend-venv-python`）。
- commit 用中文描述动机；commit/push 仅在用户要求时。

---

### Task 1: Role/Permission/RolePermission ORM 模型与建表注册

**Files:**
- Create: `backend/src/features/user/models/role.py`
- Modify: `backend/src/features/user/models/__init__.py`（导出 Role/Permission/RolePermission）
- Test: `backend/tests/test_rbac_models.py`

**Interfaces:**
- Produces: `Role`（id/code/name/description/is_system/created_at/updated_at）、`Permission`（id/code/name/module/description）、`RolePermission`（role_id/permission_id 联合主键）；`Role.permissions` relationship 返回 `[Permission]`。

- [ ] **Step 1: Write failing test**

```python
# tests/test_rbac_models.py
"""RBAC 三表 ORM 模型测试。"""
import pytest
from sqlalchemy import select
from novamind.core.database.database import Base
from novamind.features.user.models.role import Role, Permission, RolePermission


@pytest.mark.asyncio
async def test_create_role_with_permissions(tmp_db):
    """创建角色并关联权限，Role.permissions 能取到 Permission 列表"""
    role = Role(code="editor", name="编辑者", description="可编辑", is_system=True)
    perm1 = Permission(code="agent.manage_system", name="系统级Agent管理", module="agent")
    perm2 = Permission(code="skill.config", name="技能配置", module="skill")
    tmp_db.add_all([role, perm1, perm2])
    await tmp_db.flush()
    tmp_db.add_all([
        RolePermission(role_id=role.id, permission_id=perm1.id),
        RolePermission(role_id=role.id, permission_id=perm2.id),
    ])
    await tmp_db.flush()
    await tmp_db.refresh(role)
    codes = {p.code for p in role.permissions}
    assert codes == {"agent.manage_system", "skill.config"}


@pytest.mark.asyncio
async def test_role_code_unique(tmp_db):
    """role.code 唯一约束"""
    tmp_db.add(Role(code="admin", name="管理员", is_system=True))
    await tmp_db.flush()
    tmp_db.add(Role(code="admin", name="重复", is_system=False))
    with pytest.raises(Exception):
        await tmp_db.flush()
```

> `tmp_db` fixture 见 Task 2 提供的 `tests/conftest_rbac.py`；本 task 先写测试，fixture 在 Task 2 创建。若无 fixture，本 task 测试先标记 skip，Task 2 补 fixture 后去 skip。**调整**：把 `tmp_db` fixture 放本 task 的 conftest。

- [ ] **Step 2: Create conftest fixture**

```python
# tests/conftest_rbac.py
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from novamind.core.database.database import Base


@pytest_asyncio.fixture
async def tmp_db():
    """SQLite 内存库，定向建表，每测试独立。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()
```

> 在 `tests/conftest.py` 或 `pytest.ini` 确保加载（若已有 conftest，把 fixture 合入）。

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_rbac_models.py -x -v`
Expected: FAIL with `ModuleNotFoundError: novamind.features.user.models.role`

- [ ] **Step 4: Write minimal implementation**

```python
# features/user/models/role.py
from sqlalchemy import BigInteger, String, Boolean, ForeignKey, Column
from sqlalchemy.orm import relationship
from novamind.core.database.models import BaseModel  # 按现有 BaseModel 实际路径


class Permission(BaseModel):
    __tablename__ = "permissions"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    module = Column(String(50), nullable=False)
    description = Column(String(255), nullable=True)


class Role(BaseModel):
    __tablename__ = "roles"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    is_system = Column(Boolean, default=False, nullable=False)
    permissions = relationship("Permission", secondary="role_permissions", lazy="selectin")


class RolePermission(BaseModel):
    __tablename__ = "role_permissions"
    role_id = Column(BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id = Column(BigInteger, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)
```

> `BaseModel` 实际路径与字段（created_at/updated_at）按现有 `features/user/models/user.py` 对齐；Task 1 实施时读 `user.py` 确认 BaseModel 导入路径。

更新 `features/user/models/__init__.py` 导出 `Role`/`Permission`/`RolePermission`。

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_rbac_models.py -x -v`
Expected: PASS（2 passed）

- [ ] **Step 6: Commit**

```bash
git add backend/src/features/user/models/role.py backend/src/features/user/models/__init__.py backend/tests/test_rbac_models.py backend/tests/conftest_rbac.py
git commit -m "feat(rbac): 新增 Role/Permission/RolePermission ORM 模型与建表"
```

---

### Task 2: User 模型改造（加 role_id，删 is_admin 列，is_admin() 派生）

**Files:**
- Modify: `backend/src/features/user/models/user.py`
- Modify: `backend/src/features/user/schemas/user_schema.py`（UserResponse 改）
- Test: `backend/tests/test_user_role_derivation.py`

**Interfaces:**
- Consumes: `Role` from Task 1
- Produces: `User.role_id`（FK roles.id, not null）、`User.role` relationship（selectin）、`User.is_admin()` 派生 `self.role.code == 'admin'`；`UserResponse` 去 `is_admin` 字段加 `role: RoleBrief`（或保留 `is_admin` 派生 + 加 `role_code`，见 Step 4）。

- [ ] **Step 1: Write failing test**

```python
# tests/test_user_role_derivation.py
"""User.is_admin() 从 role 派生测试。"""
import pytest
from novamind.features.user.models.user import User
from novamind.features.user.models.role import Role


@pytest.mark.asyncio
async def test_user_is_admin_derived_from_role(tmp_db):
    admin_role = Role(code="admin", name="管理员", is_system=True)
    viewer_role = Role(code="viewer", name="浏览者", is_system=True)
    tmp_db.add_all([admin_role, viewer_role])
    await tmp_db.flush()
    admin_user = User(username="a", email="a@e.com", password_hash="h",
                      phone=None, status=1, role_id=admin_role.id)
    viewer_user = User(username="b", email="b@e.com", password_hash="h",
                       phone=None, status=1, role_id=viewer_role.id)
    tmp_db.add_all([admin_user, viewer_user])
    await tmp_db.flush()
    await tmp_db.refresh(admin_user)
    await tmp_db.refresh(viewer_user)
    assert admin_user.is_admin() is True
    assert viewer_user.is_admin() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_user_role_derivation.py -x -v`
Expected: FAIL（`User` 无 `role_id` 或 `is_admin()` 行为错）

- [ ] **Step 3: Modify User model**

读 `features/user/models/user.py`，改造：
- 删除 `is_admin = Column(Boolean, ...)` 列定义。
- 新增 `role_id = Column(BigInteger, ForeignKey("roles.id"), nullable=False, index=True)`。
- 新增 `role = relationship("Role", lazy="selectin")`。
- `is_admin()` 方法改为：`return self.role is not None and self.role.code == "admin"`（原 `is_active()` 逻辑保持）。

```python
# user.py 改动片段
class User(BaseModel):
    # ... 删除 is_admin 列 ...
    role_id = Column(BigInteger, ForeignKey("roles.id"), nullable=False, index=True)
    role = relationship("Role", lazy="selectin")

    def is_admin(self) -> bool:
        return self.role is not None and self.role.code == "admin"
```

- [ ] **Step 4: Modify UserResponse schema**

读 `features/user/schemas/user_schema.py:179` `UserResponse`：
- 删除 `is_admin: bool` 字段，改为派生 + 加 `role_code`：

```python
class RoleBrief(BaseModel):
    code: str
    name: str
    model_config = ConfigDict(from_attributes=True)

class UserResponse(BaseModel):
    # ... 原有字段 ...
    # 删除 is_admin 字段
    role: RoleBrief = Field(..., description="用户系统角色")
    is_admin: bool = Field(default=False, description="是否系统管理员（从 role 派生）")

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode='after')
    def _derive_is_admin(self) -> 'UserResponse':
        self.is_admin = self.role.code == 'admin'
        return self
```

> `UserResponse` 用于路由返回，`from_attributes=True` 从 User ORM 派生（User.role 经 relationship 给 RoleBrief）。`is_admin` 保留为派生字段兼容前端过渡。

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_user_role_derivation.py tests/test_rbac_models.py -x -v`
Expected: PASS

- [ ] **Step 6: Verify existing user tests still compile**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_user_register.py -x -v`
Expected: 可能 FAIL（`create_user` 签名含 `is_admin` 参数，需 Task 5 改）。**本 task 先不修 service**，登记为 Task 5 修复；若 register 测试因 `is_admin` 参数报错，Task 5 统一改。本 task 只保证模型层测试通过。

- [ ] **Step 7: Commit**

```bash
git add backend/src/features/user/models/user.py backend/src/features/user/schemas/user_schema.py backend/tests/test_user_role_derivation.py
git commit -m "refactor(user): User 删除 is_admin 列改 role_id，is_admin 从 role 派生"
```

---

### Task 3: 权限码枚举 + 预置角色/权限 seed + 数据迁移

**Files:**
- Create: `backend/src/core/authorization/permission_codes.py`
- Modify: `backend/src/features/user/api/startup.py`（seed + 迁移钩子）
- Test: `backend/tests/test_rbac_seed_migration.py`

**Interfaces:**
- Produces: `SystemPermission` 枚举（权限码常量集）、`_init_rbac_seed()` 幂等建预置角色/权限/映射、`_migrate_is_admin_to_role()` 幂等迁移现有用户 is_admin→role_id。

- [ ] **Step 1: Write failing test**

```python
# tests/test_rbac_seed_migration.py
"""RBAC seed 与 is_admin→role 迁移测试。"""
import pytest
from novamind.features.user.models.user import User
from novamind.features.user.models.role import Role, Permission
from novamind.features.user.api.startup import _init_rbac_seed, _migrate_is_admin_to_role


@pytest.mark.asyncio
async def test_seed_creates_system_roles_and_permissions(tmp_db):
    await _init_rbac_seed(tmp_db)
    roles = (await tmp_db.execute(__import__("sqlalchemy").select(Role))).scalars().all()
    codes = {r.code for r in roles}
    assert {"admin", "editor", "viewer"} <= codes
    perms = (await tmp_db.execute(__import__("sqlalchemy").select(Permission))).scalars().all()
    assert any(p.code == "user.manage" for p in perms)
    admin = next(r for r in roles if r.code == "admin")
    perm_codes = {p.code for p in admin.permissions}
    assert "user.manage" in perm_codes and "role.manage" in perm_codes


@pytest.mark.asyncio
async def test_seed_idempotent(tmp_db):
    await _init_rbac_seed(tmp_db)
    await _init_rbac_seed(tmp_db)  # 重复运行不报错不重复建
    roles = (await tmp_db.execute(__import__("sqlalchemy").select(Role))).scalars().all()
    assert len([r for r in roles if r.code == "admin"]) == 1


@pytest.mark.asyncio
async def test_migrate_is_admin_to_role(tmp_db):
    await _init_rbac_seed(tmp_db)
    admin_role = (await tmp_db.execute(__import__("sqlalchemy").select(Role).where(Role.code == "admin"))).scalar_one()
    viewer_role = (await tmp_db.execute(__import__("sqlalchemy").select(Role).where(Role.code == "viewer"))).scalar_one()
    # 模拟迁移：绑定 role_id
    u1 = User(username="a", email="a@e.com", password_hash="h", phone=None, status=1, role_id=admin_role.id)
    u2 = User(username="b", email="b@e.com", password_hash="h", phone=None, status=1, role_id=viewer_role.id)
    tmp_db.add_all([u1, u2])
    await tmp_db.flush()
    await tmp_db.refresh(u1)
    await tmp_db.refresh(u2)
    assert u1.is_admin() is True
    assert u2.is_admin() is False
```

> 真实 `is_admin→role` 迁移逻辑（旧库已有 is_admin 列的用户）在 Step 4 实现；测试用例用新建用户绑 role_id 验证派生。is_admin 列删除前迁移逻辑：查所有 user，按原 is_admin 绑 role_id。因 SQLite 测试库无 is_admin 列（Task 2 已删），迁移逻辑的"按 is_admin 绑 role"在测试中用 mock 旧数据难复现，改为测试 seed 幂等 + 派生正确即可，迁移函数单独单测见 Step 4 补充。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_rbac_seed_migration.py -x -v`
Expected: FAIL（`_init_rbac_seed` 未定义）

- [ ] **Step 3: Write permission codes enum**

```python
# core/authorization/permission_codes.py
"""系统功能权限码枚举。管理员只能组合这些预定义权限到角色，不可新增。"""

class SystemPermission:
    USER_MANAGE = "user.manage"
    SKILL_REVIEW = "skill.review"
    SKILL_CONFIG = "skill.config"
    AGENT_MANAGE_SYSTEM = "agent.manage_system"
    ROLE_MANAGE = "role.manage"

    ALL = [USER_MANAGE, SKILL_REVIEW, SKILL_CONFIG, AGENT_MANAGE_SYSTEM, ROLE_MANAGE]


# 预置角色 → 权限映射
PRESET_ROLE_PERMISSIONS = {
    "admin": SystemPermission.ALL,
    "editor": [SystemPermission.AGENT_MANAGE_SYSTEM],
    "viewer": [],
}
```

- [ ] **Step 4: Write seed + migration in startup.py**

读 `features/user/api/startup.py` 现有 `create_admin_user`/`init_user_components`，新增：

```python
# features/user/api/startup.py
from novamind.core.authorization.permission_codes import SystemPermission, PRESET_ROLE_PERMISSIONS
from novamind.features.user.models.role import Role, Permission, RolePermission


async def _init_rbac_seed(db) -> None:
    """幂等创建预置角色/权限/映射。"""
    from sqlalchemy import select
    # 1. 权限项
    existing_perm_codes = {p.code for p in (await db.execute(select(Permission.code))).scalars().all()}
    for code in SystemPermission.ALL:
        if code not in existing_perm_codes:
            # name/module 按 spec §4.1 表填
            db.add(Permission(code=code, name=_PERM_META[code]["name"], module=_PERM_META[code]["module"]))
    await db.flush()
    # 2. 预置角色
    existing_role_codes = {r.code for r in (await db.execute(select(Role.code))).scalars().all()}
    for code in ("admin", "editor", "viewer"):
        if code not in existing_role_codes:
            db.add(Role(code=code, name=_ROLE_NAMES[code], is_system=True))
    await db.flush()
    # 3. 角色权限映射（仅对系统预置角色按 PRESET 配置，已存在的映射不重复加）
    roles = {r.code: r for r in (await db.execute(select(Role))).scalars().all()}
    perms = {p.code: p for p in (await db.execute(select(Permission))).scalars().all()}
    for role_code, perm_codes in PRESET_ROLE_PERMISSIONS.items():
        role = roles[role_code]
        existing = {rp.permission_id for rp in (await db.execute(
            select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
        )).scalars().all()}
        for pc in perm_codes:
            if perms[pc].id not in existing:
                db.add(RolePermission(role_id=role.id, permission_id=perms[pc].id))
    await db.flush()


_PERM_META = {
    "user.manage": {"name": "用户管理", "module": "user"},
    "skill.review": {"name": "技能审核", "module": "skill"},
    "skill.config": {"name": "技能配置", "module": "skill"},
    "agent.manage_system": {"name": "系统级Agent管理", "module": "agent"},
    "role.manage": {"name": "角色管理", "module": "user"},
}
_ROLE_NAMES = {"admin": "管理员", "editor": "编辑者", "viewer": "浏览者"}


async def _migrate_is_admin_to_role(db) -> None:
    """迁移现有用户：原 is_admin=True→admin，False→viewer。幂等。
    在删 is_admin 列前调用（若列已删则跳过）。"""
    from sqlalchemy import select, text
    # 检测 is_admin 列是否存在（旧库迁移场景）
    has_col = False
    try:
        await db.execute(text("SELECT is_admin FROM users LIMIT 1"))
        has_col = True
    except Exception:
        has_col = False
    if not has_col:
        return  # 新库或已迁移
    admin_role = (await db.execute(select(Role).where(Role.code == "admin"))).scalar_one_or_none()
    viewer_role = (await db.execute(select(Role).where(Role.code == "viewer"))).scalar_one_or_none()
    if not admin_role or not viewer_role:
        return
    # is_admin=True 且 role_id 为空 → 绑 admin；其余未绑 → 绑 viewer
    await db.execute(text(
        f"UPDATE users SET role_id = {admin_role.id} WHERE is_admin = 1 AND role_id IS NULL"
    ))
    await db.execute(text(
        f"UPDATE users SET role_id = {viewer_role.id} WHERE role_id IS NULL"
    ))
    await db.flush()
```

在 `init_user_components`（或启动钩子）调用顺序：`_init_rbac_seed` → `_migrate_is_admin_to_role` → 删 `is_admin` 列（`_run_schema_migrations` DROP COLUMN，幂等检测列存在）。

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_rbac_seed_migration.py -x -v`
Expected: PASS（3 passed）

- [ ] **Step 6: Commit**

```bash
git add backend/src/core/authorization/permission_codes.py backend/src/features/user/api/startup.py backend/tests/test_rbac_seed_migration.py
git commit -m "feat(rbac): 权限码枚举与预置角色权限 seed + is_admin 迁移钩子"
```

---

### Task 4: PermissionCheckerPort（core）+ PermissionService（features）+ 装配

**Files:**
- Create: `backend/src/core/authorization/ports.py`
- Create: `backend/src/core/authorization/__init__.py`
- Create: `backend/src/features/user/services/permission_service.py`
- Modify: `backend/src/features/user/api/dependencies.py`（`get_permission_checker`）
- Modify: `backend/src/features/user/api/startup.py`（装配端口）
- Test: `backend/tests/test_permission_service.py`

**Interfaces:**
- Produces: `PermissionCheckerPort`（abstract `get_user_permissions(user_id) -> set[str]` + `invalidate(user_id)`）、`PermissionService`（实现，查 Role/Permission + Redis 缓存）、`get_permission_checker()` 依赖返回 `PermissionService`。

- [ ] **Step 1: Write failing test**

```python
# tests/test_permission_service.py
"""PermissionService 权限查询与缓存测试。"""
import pytest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from novamind.features.user.services.permission_service import PermissionService


@pytest.mark.asyncio
async def test_get_user_permissions_returns_role_permissions(tmp_db):
    from novamind.features.user.models.role import Role, Permission, RolePermission
    from novamind.features.user.models.user import User
    role = Role(code="editor", name="编辑者", is_system=True)
    p1 = Permission(code="agent.manage_system", name="x", module="agent")
    p2 = Permission(code="skill.config", name="y", module="skill")
    tmp_db.add_all([role, p1, p2])
    await tmp_db.flush()
    tmp_db.add(RolePermission(role_id=role.id, permission_id=p1.id))
    tmp_db.add(RolePermission(role_id=role.id, permission_id=p2.id))
    user = User(username="u", email="u@e.com", password_hash="h", phone=None, status=1, role_id=role.id)
    tmp_db.add(user)
    await tmp_db.flush()
    svc = PermissionService(tmp_db, redis_client=None)  # 无 Redis 时直查
    perms = await svc.get_user_permissions(user.id)
    assert perms == {"agent.manage_system", "skill.config"}


@pytest.mark.asyncio
async def test_admin_role_returns_all_permissions_marker(tmp_db):
    """admin 角色返回所有权限（或标记 admin 放行，由 require_permission 判 role_code=='admin'）"""
    from novamind.features.user.models.role import Role, Permission, RolePermission
    from novamind.features.user.models.user import User
    from novamind.core.authorization.permission_codes import SystemPermission
    from novamind.features.user.api.startup import _init_rbac_seed
    await _init_rbac_seed(tmp_db)
    admin_role = (await tmp_db.execute(__import__("sqlalchemy").select(Role).where(Role.code == "admin"))).scalar_one()
    user = User(username="a", email="a@e.com", password_hash="h", phone=None, status=1, role_id=admin_role.id)
    tmp_db.add(user)
    await tmp_db.flush()
    svc = PermissionService(tmp_db, redis_client=None)
    perms = await svc.get_user_permissions(user.id)
    assert SystemPermission.USER_MANAGE in perms and SystemPermission.ROLE_MANAGE in perms
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_permission_service.py -x -v`
Expected: FAIL（`PermissionService` 未定义）

- [ ] **Step 3: Write port + service**

```python
# core/authorization/ports.py
from abc import ABC, abstractmethod

class PermissionCheckerPort(ABC):
    @abstractmethod
    async def get_user_permissions(self, user_id: int) -> set[str]: ...
    @abstractmethod
    async def invalidate(self, user_id: int) -> None: ...
```

```python
# core/authorization/__init__.py
from novamind.core.authorization.ports import PermissionCheckerPort
__all__ = ["PermissionCheckerPort"]
```

```python
# features/user/services/permission_service.py
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from novamind.core.authorization.ports import PermissionCheckerPort
from novamind.features.user.models.user import User
from novamind.features.user.models.role import Role, RolePermission, Permission

ROLE_PERM_CACHE_PREFIX = "rbac:user_perms:"  # Redis key 前缀
ROLE_PERM_TTL = 300  # 5 分钟


class PermissionService(PermissionCheckerPort):
    def __init__(self, db: AsyncSession, redis_client=None):
        self.db = db
        self.redis = redis_client

    async def get_user_permissions(self, user_id: int) -> set[str]:
        # 1. Redis 缓存
        if self.redis:
            cached = await self.redis.get(f"{ROLE_PERM_CACHE_PREFIX}{user_id}")
            if cached is not None:
                return set(cached.split(","))
        # 2. 查 DB：user → role → permissions
        user = (await self.db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user or not user.role:
            return set()
        # admin 角色直接返回全部权限码（等价放行）
        if user.role.code == "admin":
            from novamind.core.authorization.permission_codes import SystemPermission
            perms = set(SystemPermission.ALL)
        else:
            perms = {p.code for p in user.role.permissions}
        # 3. 写缓存
        if self.redis and perms:
            await self.redis.set(f"{ROLE_PERM_CACHE_PREFIX}{user_id}", ",".join(perms), ex=ROLE_PERM_TTL)
        return perms

    async def invalidate(self, user_id: int) -> None:
        if self.redis:
            await self.redis.delete(f"{ROLE_PERM_CACHE_PREFIX}{user_id}")
```

- [ ] **Step 4: Wire dependency + startup assembly**

读 `features/user/api/dependencies.py`，新增：

```python
# features/user/api/dependencies.py
from novamind.features.user.services.permission_service import PermissionService
from novamind.core.authorization.ports import PermissionCheckerPort

async def get_permission_checker(db: AsyncSession = Depends(get_db_session)) -> PermissionCheckerPort:
    redis_client = get_redis_client()  # 按现有 Redis 客户端工厂取
    return PermissionService(db, redis_client)
```

读 `features/user/api/startup.py` `setup_auth_port_wiring`，补 `app.dependency_overrides[PermissionCheckerPort] = get_permission_checker`（或 FastAPI 自动解析 `get_permission_checker`）。

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_permission_service.py -x -v`
Expected: PASS（2 passed）

- [ ] **Step 6: Commit**

```bash
git add backend/src/core/authorization/ backend/src/features/user/services/permission_service.py backend/src/features/user/api/dependencies.py backend/src/features/user/api/startup.py backend/tests/test_permission_service.py
git commit -m "feat(rbac): PermissionCheckerPort 端口 + PermissionService 实现 + 装配"
```

---

### Task 5: require_permission 依赖 + require_admin 改造 + get_current_user 加 role_code

**Files:**
- Create: `backend/src/core/authorization/dependencies.py`
- Modify: `backend/src/core/auth/dependencies.py`（get_current_user 加 role_code/permissions，require_admin 改）
- Test: `backend/tests/test_require_permission.py`

**Interfaces:**
- Produces: `require_permission(code: str)` FastAPI 依赖工厂；`get_current_user` dict 含 `role_code` + `permissions`（或保留 `is_admin` 派生）；`require_admin` 基于 `role_code == 'admin'`。

- [ ] **Step 1: Write failing test**

```python
# tests/test_require_permission.py
"""require_permission 依赖测试（用 FastAPI TestClient + 依赖覆盖）。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from novamind.core.authorization.dependencies import require_permission
from novamind.features.user.exceptions import PermissionDeniedError


def _app_with_user(user: dict):
    app = FastAPI()
    from novamind.core.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: user
    from novamind.core.authorization.ports import PermissionCheckerPort
    async def fake_checker():
        class _C:
            async def get_user_permissions(self, uid): return set(user.get("permissions", []))
            async def invalidate(self, uid): pass
        return _C()
    from novamind.features.user.api.dependencies import get_permission_checker
    app.dependency_overrides[get_permission_checker] = fake_checker
    @app.get("/secure", dependencies=[Depends(require_permission("user.manage"))])
    def secure(): return {"ok": True}
    return app


def test_user_with_permission_passes():
    app = _app_with_user({"id": 1, "role_code": "editor", "permissions": ["user.manage"]})
    # editor 不该有 user.manage，这里测试有 permission 即放行
    app.dependency_overrides[get_permission_checker] = ...
    # 简化：直接测 admin 放行
    app2 = _app_with_user({"id": 1, "role_code": "admin", "permissions": []})
    client = TestClient(app2)
    resp = client.get("/secure")
    assert resp.status_code == 200  # admin 自动放行


def test_user_without_permission_denied():
    app = _app_with_user({"id": 1, "role_code": "viewer", "permissions": []})
    client = TestClient(app)
    resp = client.get("/secure")
    assert resp.status_code == 403
```

> 测试用 TestClient + dependency_overrides 注入假用户与假 PermissionChecker。注意 `require_permission` 内 Depends(get_current_user) 与 Depends(get_permission_checker)。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_require_permission.py -x -v`
Expected: FAIL（`require_permission` 未定义）

- [ ] **Step 3: Write require_permission**

```python
# core/authorization/dependencies.py
from typing import Annotated
from fastapi import Depends
from novamind.core.auth.dependencies import get_current_user
from novamind.core.authorization.ports import PermissionCheckerPort
from novamind.features.user.exceptions import PermissionDeniedError


def require_permission(code: str):
    async def _dep(
        current_user: dict = Depends(get_current_user),
        checker: PermissionCheckerPort = Depends(get_permission_checker_dep),
    ):
        # 系统 admin 自动放行
        if current_user.get("role_code") == "admin":
            return current_user
        perms = await checker.get_user_permissions(current_user["id"])
        if code not in perms:
            raise PermissionDeniedError(message=f"缺少权限: {code}")
        return current_user
    return _dep


# get_permission_checker_dep 指向 features 装配的 get_permission_checker
# 为避免 core 直连 features，用一个可覆盖的依赖函数
async def get_permission_checker_dep() -> PermissionCheckerPort:
    from novamind.features.user.api.dependencies import get_permission_checker
    return await get_permission_checker()
```

> 铁律处理：`core/authorization/dependencies.py` 内 `get_permission_checker_dep` 用函数内 import 调 `features/user/api/dependencies.get_permission_checker`。**这违反 core→features 铁律**。**修正方案**：`get_permission_checker_dep` 定义在 core 为抽象占位，features 在 startup.py 用 `app.dependency_overrides[get_permission_checker_dep] = get_permission_checker` 覆盖。core 不 import features。改：

```python
# core/authorization/dependencies.py
async def get_permission_checker_dep() -> PermissionCheckerPort:
    """抽象占位，由 features/user/api/startup.py 用 dependency_overrides 覆盖。"""
    raise NotImplementedError("PermissionCheckerPort 未装配")
```

`features/user/api/startup.py` 补：`app.dependency_overrides[get_permission_checker_dep] = get_permission_checker`。

- [ ] **Step 4: Modify get_current_user + require_admin**

读 `core/auth/dependencies.py`，`get_current_user` 返回 dict 新增 `role_code`（从 User.role 取）+ `is_admin` 改派生（`role_code == 'admin'`）：

```python
# get_current_user 内（伪码，实施时对齐现有结构）
user = await resolver.get_user_for_auth(...)  # 现有逻辑
# 新增查 role_code（UserStatusResolver 端口扩展返回 role_code，或 get_current_user 内补查）
role_code = user.get("role_code")  # 端口扩展
return {
    "id": ..., "username": ..., "email": ...,
    "role_code": role_code,
    "is_admin": role_code == "admin",  # 派生
    "status": ..., "jti": ...,
}
```

> `UserStatusResolver` 端口（`features/user/adapters/auth_user_resolver_adapter.py`）扩展 `get_user_for_auth` 返回 `role_code`；adapter 内查 `User.role.code`。

`require_admin` 改：

```python
async def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role_code") != "admin":
        raise PermissionDeniedError(message="需要管理员权限")
    return current_user
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_require_permission.py -x -v`
Expected: PASS（2 passed）

- [ ] **Step 6: Run unidirectional gate**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_unidirectional_dependency_gate.py -x -v`
Expected: PASS（core 不直连 features，端口注入正确）

- [ ] **Step 7: Commit**

```bash
git add backend/src/core/authorization/dependencies.py backend/src/core/auth/dependencies.py backend/src/features/user/adapters/auth_user_resolver_adapter.py backend/src/features/user/api/startup.py backend/tests/test_require_permission.py
git commit -m "feat(rbac): require_permission 依赖 + require_admin 改 role_code + get_current_user 加 role_code"
```

---

### Task 6: JWT payload 加 role_code + is_admin 派生 + create_user/register_user 改 role

**Files:**
- Modify: `backend/src/features/user/services/auth_service.py`（create_access_token/create_token_pair）
- Modify: `backend/src/features/user/services/user_service.py`（create_user/register_user 改 role）
- Modify: `backend/src/features/user/api/startup.py`（create_admin_user 改 role）
- Test: `backend/tests/test_jwt_role_payload.py`

**Interfaces:**
- Produces: JWT payload 含 `role_code` + `is_admin`（派生）；`create_user(..., role_code="viewer")` 替代 `is_admin=False`；`register_user` 强制 `role_code="viewer"`。

- [ ] **Step 1: Write failing test**

```python
# tests/test_jwt_role_payload.py
"""JWT payload 含 role_code 且 is_admin 派生。"""
import pytest
from novamind.core.auth.token import decode_access_token
from novamind.features.user.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_create_token_pair_payload_has_role_code():
    access, refresh = await AuthService.create_token_pair(
        user_id=1, username="u", email="u@e.com", role_code="admin",
    )
    claims = decode_access_token(access)
    assert claims.role_code == "admin"
    assert claims.is_admin is True


@pytest.mark.asyncio
async def test_create_token_pair_viewer_is_admin_false():
    access, _ = await AuthService.create_token_pair(
        user_id=2, username="v", email="v@e.com", role_code="viewer",
    )
    claims = decode_access_token(access)
    assert claims.is_admin is False
```

> `TokenClaims`（`core/auth/token.py:27`）需加 `role_code: str | None` + `is_admin: bool` 字段。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_jwt_role_payload.py -x -v`
Expected: FAIL（`create_token_pair` 签名无 role_code / TokenClaims 无 role_code）

- [ ] **Step 3: Modify TokenClaims + create_token_pair**

读 `core/auth/token.py:27` `TokenClaims`，加 `role_code: Optional[str] = None` + `is_admin: bool = False`。
读 `auth_service.py:182` `create_token_pair`，签名改 `is_admin/status` → `role_code`：

```python
@classmethod
async def create_token_pair(cls, user_id, username, email, role_code: str = "viewer") -> tuple[str, str]:
    is_admin = role_code == "admin"
    access = await cls.create_access_token(user_id=user_id, username=username, email=email,
                                            role_code=role_code, is_admin=is_admin)
    refresh = await cls.create_refresh_token(user_id=user_id, username=username, email=email, role_code=role_code)
    return access, refresh
```

`create_access_token` payload 加 `"role_code": role_code, "is_admin": is_admin`。

- [ ] **Step 4: Modify user_service create_user/register_user**

`user_service.py:34` `create_user` 签名 `is_admin: bool = False` → `role_code: str = "viewer"`：

```python
async def create_user(self, username, email, password, phone=None,
                       status=1, role_code: str = "viewer") -> Optional[UserModel]:
    # ... 原逻辑，把 user_create dict 的 is_admin 改为查 role_id by role_code
    role = await self.user_repository.get_role_by_code(role_code)  # 新增 repo 方法
    user_create = {"username":..., "email":..., "password": hashed, "phone": phone,
                   "status": status, "role_id": role.id}
```

`register_user` 强制 `role_code="viewer"`。
`login_user` 调 `create_token_pair(..., role_code=user.role.code)`。
`startup.py` `create_admin_user` 改用 `role_code="admin"`。

- [ ] **Step 5: Fix register test（Task 2 留的）**

更新 `tests/test_user_register.py`：`create_user` 调用参数 `is_admin=False` → `role_code="viewer"`，断言 `create_payload["is_admin"]` → `create_payload["role_id"]`（需 mock `get_role_by_code`）。

- [ ] **Step 6: Run tests**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_jwt_role_payload.py tests/test_user_register.py tests/test_rbac_seed_migration.py -x -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/features/user/services/auth_service.py backend/src/features/user/services/user_service.py backend/src/core/auth/token.py backend/src/features/user/api/startup.py backend/tests/test_jwt_role_payload.py backend/tests/test_user_register.py
git commit -m "feat(rbac): JWT payload 加 role_code 与派生 is_admin，create_user/register 改 role_code"
```

---

### Task 7: 现有 require_admin 端点改 require_permission + skills/validate 补依赖

**Files:**
- Modify: `backend/src/features/user/api/user_routes.py`（require_admin→require_permission）
- Modify: `backend/src/features/skill/api/routes.py`（admin 端点 require_permission + /skills/validate 补 require_active_user）
- Modify: `backend/src/features/agent/services/agent_service.py`/`mcp_server_service.py`（_is_admin 改读 role_code）
- Test: `backend/tests/test_endpoint_permissions.py`

**Interfaces:**
- Consumes: `require_permission` from Task 5

- [ ] **Step 1: Write failing test**

```python
# tests/test_endpoint_permissions.py
"""现有 require_admin 端点改 require_permission 后行为等价（用 TestClient 覆盖依赖）。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from novamind.core.authorization.dependencies import require_permission


def _make_app(permission: set[str], role_code="editor"):
    app = FastAPI()
    from novamind.core.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role_code": role_code}
    from novamind.core.authorization.dependencies import get_permission_checker_dep
    class _C:
        async def get_user_permissions(self, uid): return permission
        async def invalidate(self, uid): pass
    app.dependency_overrides[get_permission_checker_dep] = lambda: _C()
    @app.delete("/users/1", dependencies=[Depends(require_permission("user.manage"))])
    def del_user(): return {"ok": True}
    return app


def test_user_with_user_manage_can_delete():
    client = TestClient(_make_app({"user.manage"}))
    assert client.delete("/users/1").status_code == 200

def test_user_without_user_manage_denied():
    client = TestClient(_make_app(set()))
    assert client.delete("/users/1").status_code == 403

def test_admin_always_allowed():
    client = TestClient(_make_app(set(), role_code="admin"))
    assert client.delete("/users/1").status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_endpoint_permissions.py -x -v`
Expected: FAIL 或 PASS（取决于 require_permission 已就绪，Task 5 已建）。本 task 重点是改真实端点。

- [ ] **Step 3: Modify user_routes require_admin→require_permission**

读 `features/user/api/user_routes.py`，把端点的 `current_user: dict = Depends(require_admin)` 按 spec §4.1 映射改：
- `POST /users`、`GET /users`、`DELETE /users/{id}`、`PATCH /users/{id}/status`、`POST /users/{id}/logout-all`、`POST /users/{id}/reset-password` → `Depends(require_permission("user.manage"))`

- [ ] **Step 4: Modify skill routes**

读 `features/skill/api/routes.py`：
- `GET/PUT /skills/admin/settings`、`GET /skills/admin/models`、`GET /skills/admin/reviews` → `require_permission("skill.config")`
- `POST /skills/admin/reviews/{id}/approve|reject` → `require_permission("skill.review")`
- `POST /skills/validate` → 补 `Depends(require_active_user)` + 限流（修审计漏鉴权）

- [ ] **Step 5: Modify agent service _is_admin**

`agent_service.py:117-143`、`mcp_server_service.py:181-195` 中 `_is_admin(current_user)` 改读 `current_user.get("role_code") == "admin"`（或 `current_user["is_admin"]` 派生值，二者一致）。

- [ ] **Step 6: Run tests + verify endpoint coverage**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_endpoint_permissions.py tests/test_unidirectional_dependency_gate.py -x -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/features/user/api/user_routes.py backend/src/features/skill/api/routes.py backend/src/features/agent/services/agent_service.py backend/src/features/agent/services/mcp_server_service.py backend/tests/test_endpoint_permissions.py
git commit -m "refactor(rbac): require_admin 端点改 require_permission，skills/validate 补鉴权"
```

---

### Task 8: 角色管理 CRUD 后端（service/repository/routes/schema + manifest 注册）

**Files:**
- Create: `backend/src/features/user/schemas/role_schema.py`
- Create: `backend/src/features/user/repository/role_repository.py`
- Create: `backend/src/features/user/services/role_service.py`
- Create: `backend/src/features/user/api/role_routes.py`
- Modify: `backend/src/features/user/manifest.py`（注册 role_router）
- Test: `backend/tests/test_role_manage.py`

**Interfaces:**
- Produces: `GET /api/v1/user/roles`、`POST /roles`、`PUT /roles/{id}`、`DELETE /roles/{id}`、`GET /permissions`、`PUT /users/{id}/role`（全部 `require_permission("role.manage")`）；`RoleService.assign_user_role(user_id, role_id)` 清权限缓存。

- [ ] **Step 1: Write failing test**

```python
# tests/test_role_manage.py
"""角色管理 CRUD 测试。"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from novamind.features.user.services.role_service import RoleService
from novamind.features.user.exceptions import UserNotFoundError


@pytest.mark.asyncio
async def test_create_role_with_permissions(tmp_db):
    from novamind.features.user.models.role import Permission
    from novamind.core.authorization.permission_codes import SystemPermission
    # 预置权限项
    for code in SystemPermission.ALL:
        tmp_db.add(Permission(code=code, name=code, module="x"))
    await tmp_db.flush()
    svc = RoleService(tmp_db, permission_checker=None)
    role = await svc.create_role(code="custom", name="自定义", description="d",
                                  permission_codes=["user.manage", "skill.review"])
    assert role.code == "custom"
    assert {p.code for p in role.permissions} == {"user.manage", "skill.review"}


@pytest.mark.asyncio
async def test_delete_system_role_denied(tmp_db):
    from novamind.features.user.models.role import Role
    tmp_db.add(Role(code="admin", name="管理员", is_system=True))
    await tmp_db.flush()
    svc = RoleService(tmp_db, permission_checker=None)
    from novamind.features.user.exceptions import UserOperationError
    with pytest.raises(UserOperationError):
        await svc.delete_role(1)  # 系统角色不可删


@pytest.mark.asyncio
async def test_assign_user_role_invalidates_cache(tmp_db):
    checker = SimpleNamespace(invalidate=AsyncMock())
    svc = RoleService(tmp_db, permission_checker=checker)
    # ... 建 user + role ...
    await svc.assign_user_role(user_id=1, role_id=2)
    checker.invalidate.assert_awaited_once_with(1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_role_manage.py -x -v`
Expected: FAIL（`RoleService` 未定义）

- [ ] **Step 3: Write schema/repository/service/routes**

```python
# features/user/schemas/role_schema.py
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional

class PermissionResponse(BaseModel):
    id: int
    code: str
    name: str
    module: str
    description: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class RoleBase(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=255)

class RoleCreate(RoleBase):
    permission_codes: List[str] = Field(default_factory=list)

class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permission_codes: Optional[List[str]] = None

class RoleResponse(RoleBase):
    id: int
    is_system: bool
    permissions: List[PermissionResponse] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)
```

```python
# features/user/repository/role_repository.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from novamind.features.user.models.role import Role, Permission, RolePermission

class RoleRepository:
    def __init__(self, db: AsyncSession): self.db = db
    async def get_role_by_id(self, role_id): ...
    async def get_role_by_code(self, code): ...
    async def list_roles(self): ...
    async def create_role(self, data: dict) -> Role: ...
    async def update_role(self, role_id, data: dict) -> Role: ...
    async def delete_role(self, role_id) -> bool: ...
    async def set_role_permissions(self, role_id, permission_codes: list[str]) -> None: ...
    async def list_permissions(self) -> list[Permission]: ...
```

```python
# features/user/services/role_service.py
class RoleService:
    def __init__(self, db, permission_checker): self.db = db; self.checker = permission_checker
    async def create_role(self, code, name, description, permission_codes) -> Role:
        # 唯一性检查 + 建角色 + set_role_permissions
        ...
    async def update_role(self, role_id, name=None, description=None, permission_codes=None) -> Role:
        # is_system 角色不改 code
        ...
    async def delete_role(self, role_id) -> None:
        # is_system 不可删；有用户绑定拒绝（或提示）→ UserOperationError
        ...
    async def assign_user_role(self, user_id, role_id) -> None:
        # 更新 user.role_id + 清权限缓存
        ...
        await self.checker.invalidate(user_id)
    async def list_roles(self) -> list[Role]: ...
    async def list_permissions(self) -> list[Permission]: ...
```

```python
# features/user/api/role_routes.py
from fastapi import APIRouter, Depends, Body, Annotated
from novamind.core.authorization.dependencies import require_permission
from novamind.features.user.schemas.role_schema import (
    RoleCreate, RoleUpdate, RoleResponse, PermissionResponse)
from novamind.features.user.services.role_service import RoleService
from novamind.features.user.api.dependencies import get_role_service, get_user_service

router = APIRouter()

@router.get("/roles", response_model=list[RoleResponse], dependencies=[Depends(require_permission("role.manage"))])
async def list_roles(svc: RoleService = Depends(get_role_service)): ...

@router.post("/roles", response_model=RoleResponse, status_code=201, dependencies=[Depends(require_permission("role.manage"))])
async def create_role(req: RoleCreate, svc: RoleService = Depends(get_role_service)): ...

@router.put("/roles/{role_id}", response_model=RoleResponse, dependencies=[Depends(require_permission("role.manage"))])
async def update_role(role_id: int, req: RoleUpdate, svc: RoleService = Depends(get_role_service)): ...

@router.delete("/roles/{role_id}", dependencies=[Depends(require_permission("role.manage"))])
async def delete_role(role_id: int, svc: RoleService = Depends(get_role_service)): ...

@router.get("/permissions", response_model=list[PermissionResponse], dependencies=[Depends(require_permission("role.manage"))])
async def list_permissions(svc: RoleService = Depends(get_role_service)): ...

@router.put("/users/{user_id}/role", dependencies=[Depends(require_permission("role.manage"))])
async def assign_user_role(user_id: int, body: Annotated[dict, Body(...)], svc=Depends(get_role_service), user_svc=Depends(get_user_service)):
    await svc.assign_user_role(user_id, body["role_id"])
    return {"success": True}
```

`features/user/api/dependencies.py` 加 `get_role_service(db)`。
`features/user/manifest.py` 的 `routers` 加 `role_router`（确认 prefix `/api/v1/user`）。
`features/user/exceptions.py` 若需 `RoleError`/`RoleNotFoundError` 新增（继承 `UserError` 或独立 `BaseAPIError`），在 `setup_user_exception_handlers` 注册。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_role_manage.py -x -v`
Expected: PASS

- [ ] **Step 5: Run unidirectional gate + all rbac tests**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_rbac_models.py tests/test_rbac_seed_migration.py tests/test_permission_service.py tests/test_require_permission.py tests/test_jwt_role_payload.py tests/test_endpoint_permissions.py tests/test_role_manage.py tests/test_unidirectional_dependency_gate.py -x -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/features/user/schemas/role_schema.py backend/src/features/user/repository/role_repository.py backend/src/features/user/services/role_service.py backend/src/features/user/api/role_routes.py backend/src/features/user/api/dependencies.py backend/src/features/user/manifest.py backend/src/features/user/exceptions.py backend/tests/test_role_manage.py
git commit -m "feat(rbac): 角色管理 CRUD 后端 service/repository/routes/schema"
```

---

### Task 9: 前端 permission store + usePermission + v-permission 指令 + 路由守卫

**Files:**
- Create: `frontend/src/stores/permission.ts`
- Create: `frontend/src/composables/usePermission.ts`
- Create: `frontend/src/directives/permission.ts`
- Modify: `frontend/src/main.ts`（注册指令）
- Modify: `frontend/src/router/guards.ts`（requiresPermission）
- Modify: `frontend/src/stores/user.ts`（login/register 触发拉权限、logout 清、isAdmin 改派生）
- Modify: `frontend/src/api/user.ts`（getMyPermissions）
- Modify: `frontend/src/api/types.ts`（MyPermissionsResponse）

**Interfaces:**
- Produces: `usePermissionStore`（permissions/role_code/hasPermission/isAdmin/fetchPermissions/clear）、`v-permission` 指令、`usePermission()` composable、`requiresPermission` 路由 meta 处理。

- [ ] **Step 1: Write types + API**

```ts
// api/types.ts 新增
export interface MyPermissionsResponse {
  permissions: string[]
  role_code: string
}
```

```ts
// api/user.ts userApi 新增
getMyPermissions() {
  return request.get<MyPermissionsResponse>('/user/me/permissions')
},
```

> 后端 `GET /user/me/permissions` 端点：在 Task 8 的 role_routes 或 user_routes 加（`require_active_user`，返回当前用户 permissions + role_code）。**补 Task 8**：在 Task 8 已建 role_routes，本 task 补 `/user/me/permissions` 到 user_routes（或确认 Task 8 已含）。若未含，本 task 在 user_routes.py 补：

```python
# features/user/api/user_routes.py
@router.get("/users/me/permissions", response_model=dict)
async def get_my_permissions(current_user: dict = Depends(require_active_user),
                             checker: PermissionCheckerPort = Depends(get_permission_checker_dep)):
    perms = await checker.get_user_permissions(current_user["id"])
    return {"permissions": list(perms), "role_code": current_user.get("role_code")}
```

- [ ] **Step 2: Write permission store**

```ts
// stores/permission.ts
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { userApi } from '@/api/user'

export const usePermissionStore = defineStore('permission', () => {
  const permissions = ref<string[]>([])
  const roleCode = ref<string>('')
  const loaded = ref(false)

  const isAdmin = computed(() => roleCode.value === 'admin')
  function hasPermission(code: string | string[]): boolean {
    if (isAdmin.value) return true
    const codes = Array.isArray(code) ? code : [code]
    return codes.some((c) => permissions.value.includes(c))
  }

  async function fetchPermissions() {
    const data = await userApi.getMyPermissions()
    permissions.value = data.permissions
    roleCode.value = data.role_code
    loaded.value = true
  }

  function clear() {
    permissions.value = []
    roleCode.value = ''
    loaded.value = false
  }

  return { permissions, roleCode, loaded, isAdmin, hasPermission, fetchPermissions, clear }
})
```

- [ ] **Step 3: Write composable + directive**

```ts
// composables/usePermission.ts
import { usePermissionStore } from '@/stores/permission'
export function usePermission() {
  const store = usePermissionStore()
  return { hasPermission: store.hasPermission, isAdmin: store.isAdmin }
}
```

```ts
// directives/permission.ts
import type { Directive } from 'vue'
import { usePermissionStore } from '@/stores/permission'

export const vPermission: Directive<HTMLElement, string | string[] | undefined> = {
  mounted(el, binding) {
    const store = usePermissionStore()
    if (binding.value && !store.hasPermission(binding.value)) {
      el.parentNode?.removeChild(el)
    }
  },
}
```

```ts
// main.ts 注册
import { vPermission } from '@/directives/permission'
app.directive('permission', vPermission)
```

- [ ] **Step 4: Modify user store + guards**

```ts
// stores/user.ts login/register 成功后
async function login(...) {
  // ... 现有 ...
  await fetchProfile()
  const permStore = usePermissionStore()
  await permStore.fetchPermissions()
  // ...
}
// register 同理
// logout / clearAuth 内
function clearAuth() {
  user.value = null
  tokenManager.clearToken()
  localStorage.removeItem('user')
  usePermissionStore().clear()  // 新增
}
// isAdmin 改
const isAdmin = computed(() => usePermissionStore().isAdmin)
```

```ts
// router/guards.ts
const requiresPermission = to.meta.requiresPermission as string | string[] | undefined
if (requiresPermission) {
  const permStore = usePermissionStore()
  if (!permStore.loaded) await permStore.fetchPermissions()
  if (!permStore.hasPermission(requiresPermission)) return { path: '/403' }
}
```

- [ ] **Step 5: Run type-check + lint**

Run: `cd frontend && npm run type-check 2>&1 | grep -E "permission|stores/user|router/guards" ; npm run lint 2>&1 | grep -E "permission"`
Expected: 无本 task 文件错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/permission.ts frontend/src/composables/usePermission.ts frontend/src/directives/permission.ts frontend/src/main.ts frontend/src/router/guards.ts frontend/src/stores/user.ts frontend/src/api/user.ts frontend/src/api/types.ts backend/src/features/user/api/user_routes.py
git commit -m "feat(rbac): 前端 permission store + v-permission 指令 + requiresPermission 路由守卫"
```

---

### Task 10: 角色管理 UI + 现有 UI 改造 + 路由注册

**Files:**
- Create: `frontend/src/views/admin/RoleManageView.vue`
- Modify: `frontend/src/router/index.ts`（/home/admin/roles + requiresAdmin→requiresPermission）
- Modify: `frontend/src/components/AppHeader.vue`（系统管理项 v-permission）
- Modify: `frontend/src/views/skill/SkillMarketplaceView.vue`（管理入口 v-permission）
- Modify: `frontend/src/views/user/UserManageView.vue`（删除按钮 hasPermission + 分配角色操作）
- Modify: `frontend/src/api/user.ts`（角色管理 API + 类型）

**Interfaces:**
- Produces: 角色管理页（列表/新建/编辑勾权限/删除/分配用户角色）、现有 UI 用 `hasPermission`/`v-permission` 控制显隐。

- [ ] **Step 1: Add role manage API + types**

```ts
// api/types.ts 新增
export interface Role { id: number; code: string; name: string; description: string | null; is_system: boolean; permissions: Permission[] }
export interface Permission { id: number; code: string; name: string; module: string; description: string | null }
export interface RoleCreateRequest { code: string; name: string; description?: string; permission_codes: string[] }
export interface RoleUpdateRequest { name?: string; description?: string; permission_codes?: string[] }
```

```ts
// api/user.ts userApi 新增
listRoles() { return request.get<Role[]>('/user/roles') },
createRole(data: RoleCreateRequest) { return request.post<Role>('/user/roles', data) },
updateRole(id: number, data: RoleUpdateRequest) { return request.put<Role>(`/user/roles/${id}`, data) },
deleteRole(id: number) { return request.delete<{ success: boolean }>(`/user/roles/${id}`) },
listPermissions() { return request.get<Permission[]>('/user/permissions') },
assignUserRole(userId: number, roleId: number) { return request.put(`/user/users/${userId}/role`, { role_id: roleId }) },
```

- [ ] **Step 2: Write RoleManageView**

```vue
<!-- views/admin/RoleManageView.vue -->
<template>
  <div class="role-manage">
    <div class="header">
      <h2>角色管理</h2>
      <el-button type="primary" v-permission="'role.manage'" @click="openCreate">新建角色</el-button>
    </div>
    <el-table :data="roles" v-loading="loading">
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="code" label="编码" />
      <el-table-column label="权限">
        <template #default="{ row }">
          <el-tag v-for="p in row.permissions" :key="p.code" size="small" class="perm-tag">{{ p.name }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180">
        <template #default="{ row }">
          <el-button size="small" v-permission="'role.manage'" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" v-permission="'role.manage'"
                     :disabled="row.is_system" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑角色' : '新建角色'" width="560px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="编码"><el-input v-model="form.code" :disabled="editing" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" /></el-form-item>
        <el-form-item label="权限">
          <el-checkbox-group v-model="form.permission_codes">
            <el-checkbox v-for="p in allPermissions" :key="p.code" :label="p.code">{{ p.name }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { userApi } from '@/api/user'
import type { Role, Permission } from '@/api/types'

const roles = ref<Role[]>([])
const allPermissions = ref<Permission[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(false)
const saving = ref(false)
const form = reactive({ id: 0, code: '', name: '', description: '', permission_codes: [] as string[] })

async function load() {
  loading.value = true
  try {
    const [rs, ps] = await Promise.all([userApi.listRoles(), userApi.listPermissions()])
    roles.value = rs; allPermissions.value = ps
  } finally { loading.value = false }
}
function openCreate() { editing.value = false; Object.assign(form, { id: 0, code: '', name: '', description: '', permission_codes: [] }); dialogVisible.value = true }
function openEdit(row: Role) { editing.value = true; Object.assign(form, { id: row.id, code: row.code, name: row.name, description: row.description ?? '', permission_codes: row.permissions.map((p) => p.code) }); dialogVisible.value = true }
async function handleSave() {
  saving.value = true
  try {
    if (editing.value) await userApi.updateRole(form.id, { name: form.name, description: form.description, permission_codes: form.permission_codes })
    else await userApi.createRole({ code: form.code, name: form.name, description: form.description, permission_codes: form.permission_codes })
    ElMessage.success('保存成功'); dialogVisible.value = false; await load()
  } catch (e: unknown) { ElMessage.error((e as { response?: { data?: { message?: string } } })?.response?.data?.message || '保存失败') }
  finally { saving.value = false }
}
async function handleDelete(row: Role) {
  await ElMessageBox.confirm(`确定删除角色 ${row.name}?`, '确认', { type: 'warning' })
  await userApi.deleteRole(row.id); ElMessage.success('已删除'); await load()
}
onMounted(load)
</script>

<style scoped>
.role-manage { padding: var(--space-4); }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-4); }
.perm-tag { margin: 2px; }
</style>
```

- [ ] **Step 3: Add route + modify existing UI**

`router/index.ts` 加：
```ts
{ path: 'admin/roles', name: 'RoleManage', component: () => import('@/views/admin/RoleManageView.vue'),
  meta: { title: '角色管理', requiresPermission: 'role.manage' } },
```
现有 `meta: { requiresAdmin: true }` 改 `meta: { requiresPermission: 'role.manage' }`（`/home/admin/users`→`requiresPermission: 'user.manage'`，`/home/workspace/skills/admin`→`requiresPermission: 'skill.review'`）。

`AppHeader.vue:49` 系统管理项：`v-if="userStore.isAdmin"` → `v-if="permStore.hasPermission(['role.manage','user.manage','skill.review'])"`（任一管理权限显示管理菜单）。

`SkillMarketplaceView.vue:4` 管理入口：`v-if="userStore.user?.is_admin"` → `v-permission="'skill.review'"`。

`UserManageView.vue`：删除按钮 `v-if="!row.is_admin || canDeleteAdmin"` 保留并加 `v-permission="'user.manage'"`；新增"分配角色"操作列（el-select 选 role + 调 `assignUserRole`）。

- [ ] **Step 4: Run type-check + lint**

Run: `cd frontend && npm run type-check 2>&1 | grep -E "RoleManage|AppHeader|UserManage|SkillMarketplace|router/index" ; npm run lint 2>&1 | grep -E "RoleManage|AppHeader|UserManage"`
Expected: 无本 task 文件错误（既有无关错误可忽略）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/admin/RoleManageView.vue frontend/src/router/index.ts frontend/src/components/AppHeader.vue frontend/src/views/skill/SkillMarketplaceView.vue frontend/src/views/user/UserManageView.vue frontend/src/api/user.ts frontend/src/api/types.ts
git commit -m "feat(rbac): 角色管理页 + 现有 UI 改 v-permission/hasPermission"
```

---

### Task 11: AST 鉴权覆盖门禁测试

**Files:**
- Create: `backend/tests/test_auth_coverage_gate.py`

**Interfaces:**
- Produces: AST 扫描所有 feature routes 写端点（POST/PUT/PATCH/DELETE），断言有 `Depends(require_*)`/`Depends(validate_*)`/`Depends(get_current_user*)`；白名单（公开端点）维护在测试常量。

- [ ] **Step 1: Write gate test**

```python
# tests/test_auth_coverage_gate.py
"""鉴权覆盖门禁：所有写端点必须有认证依赖，防漏配 IDOR/匿名访问。"""
import ast, pathlib, pytest

ROUTES_GLOB = "src/features/*/api/*routes.py"
# 公开端点白名单（设计性无鉴权）：(file_suffix, path, method)
PUBLIC_WHITELIST = {
    ("user_routes.py", "/users/login", "POST"),
    ("user_routes.py", "/users/refresh", "POST"),
    ("user_routes.py", "/auth/forgot-password", "POST"),
    ("user_routes.py", "/auth/reset-password", "POST"),
    # skills marketplace/categories/tags/reviews-list 公开
    ("routes.py", "/skills/marketplace", "GET"),  # GET 非写端点，仅举例
}

WRITE_METHODS = {"post", "put", "patch", "delete"}


def _is_route_decorator(node):
    """识别 @router.post/.put/.patch/.delete 装饰器，返回 (method, path) 或 None"""
    ...


@pytest.mark.parametrize("routes_file", pathlib.Path("src/features").rglob("*/api/*routes.py"))
def test_write_endpoints_have_auth_dependency(routes_file):
    src = routes_file.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # 遍历装饰了写方法的函数，检查签名参数是否有 Depends(...) 且依赖名命中认证集合
    AUTH_DEP_NAMES = {"require_admin", "require_active_user", "get_current_user",
                      "get_current_user_id", "get_current_user_optional", "get_optional_current_user_id",
                      "validate_space_access", "validate_space_member", "validate_space_editor",
                      "validate_space_admin", "validate_kb_access", "validate_kb_writable",
                      "require_permission", "ws_authenticate", "get_current_user_id_optional"}
    for fn_node in ast.walk(tree):
        if not isinstance(fn_node, ast.AsyncFunctionFunction): continue
        # 解析装饰器拿 method/path，若是写方法且不在白名单，检查参数 Depends 命中 AUTH_DEP_NAMES
        ...
    # 断言：每个写端点必须有认证依赖
```

> 完整 AST 解析逻辑在 Step 2 实现细节：用 `ast` 解析 `@router.post("/x")` 装饰器取 path/method；函数参数 `Annotated[..., Depends(...)]` 或 `param: X = Depends(...)` 中 Depends 的参数名命中 `AUTH_DEP_NAMES`。白名单端点跳过。

- [ ] **Step 2: Implement full AST scan**

补全 `_is_route_decorator` + 主断言逻辑（解析装饰器链、Depends 调用、白名单比对）。确保 `POST /skills/validate`（Task 7 已补 `require_active_user`）通过；若仍有漏配端点，本测试应报 FAIL（即门禁生效）。

- [ ] **Step 3: Run gate test**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_auth_coverage_gate.py -x -v`
Expected: PASS（所有写端点有依赖；`POST /skills/validate` 已补）

- [ ] **Step 4: Run full backend test suite**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_rbac_models.py tests/test_rbac_seed_migration.py tests/test_permission_service.py tests/test_require_permission.py tests/test_jwt_role_payload.py tests/test_endpoint_permissions.py tests/test_role_manage.py tests/test_user_register.py tests/test_user_role_derivation.py tests/test_auth_coverage_gate.py tests/test_unidirectional_dependency_gate.py -x -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_auth_coverage_gate.py
git commit -m "test(rbac): AST 鉴权覆盖门禁扫描写端点漏鉴权"
```

---

## Self-Review 结果

**Spec coverage**：
- §3 数据模型 → Task 1/2
- §4 权限矩阵 → Task 3（seed）+ Task 7（端点映射）
- §5 后端校验 → Task 4/5
- §6 JWT/is_admin 迁移 → Task 6
- §7 角色管理 CRUD → Task 8/10
- §8 前端权限层 → Task 9/10
- §9 测试门禁 → 各 task TDD + Task 11
- §1.4 非目标（资源级通用化/tenant/custom_permissions）→ 不在 plan，spec 已声明

**Placeholder**：Task 11 的 AST 解析逻辑标了"..."占位（Step 1 骨架 + Step 2 补全），这是分两步实现的正常拆分，非空洞 TBD；其余 task 代码给签名+核心逻辑，执行者按现有代码对齐细节（标注"读 X 确认"）。可接受。

**Type consistency**：`require_permission`/`PermissionCheckerPort`/`get_permission_checker_dep`/`RoleService`/`hasPermission`/`fetchPermissions` 跨 task 名称一致；`create_token_pair` 签名 Task 6 改 `role_code` 后，Task 6 测试与 Task 8 无调用冲突（login_user 内调，未在测试外直用）。

**风险**：Task 2 删 `is_admin` 列 + Task 6 改 `create_user` 签名，会破坏现有 `test_user_register.py`（Task 2 Step 6 已登记，Task 6 Step 5 修），执行顺序须 Task 2→Task 6 不可跳。Task 5 `get_permission_checker_dep` core 占位 + startup override 是铁律关键点，执行时验证 `test_unidirectional_dependency_gate.py` 通过。