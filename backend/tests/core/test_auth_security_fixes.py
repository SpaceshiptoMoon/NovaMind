# -*- coding: utf-8 -*-
"""鉴权体系安全修复回归测试。

覆盖 2026-08-30 审计修复批次：
1. P0：改密/重置密码链路不再经 UserUpdate（哈希 97 字符被 max_length=30 拒绝）
2. P1：认证链 token 级黑名单（jti）检查 —— 登出后 access token 立即失效
3. P2：强制改密服务端门禁 —— must_change_password 用户访问非豁免端点被 403 拦截
4. P2：RBAC 角色权限变更失效该角色下所有用户的权限缓存
"""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from novamind.core.auth.dependencies import (
    get_current_user,
    get_current_user_optional,
    get_user_status_resolver,
)
from novamind.core.auth.exceptions import PasswordChangeRequiredError
from novamind.core.authorization.ports import PermissionCheckerPort
from novamind.core.middleware.base_exception_handler import (
    BaseAPIError,
    create_error_handler,
    global_exception_handler,
)
from novamind.features.user.services.auth_service import AuthService

pytestmark = pytest.mark.unit


# ==================== 公共假实现 ====================


class _FakeResolver:
    """返回固定活跃用户的 UserStatusResolver 假实现。"""

    def __init__(self, must_change_password: bool = False):
        self.must_change_password = must_change_password

    async def get_user_for_auth(self, user_id: int):
        return {
            "id": user_id,
            "username": "u",
            "email": "u@t.com",
            "role_code": "viewer",
            "is_admin": False,
            "status": 1,
            "is_active": True,
            "is_deleted": False,
            "must_change_password": self.must_change_password,
        }


def _patch_blacklists(monkeypatch, *, revoked: bool = False):
    """屏蔽 Redis 黑名单查询，返回受控结果。"""
    from novamind.core.auth import dependencies as auth_deps

    async def _fake_revoked(jti):
        return revoked

    async def _fake_user_blacklisted(user_id, token_iat=None):
        return False

    monkeypatch.setattr(auth_deps, "is_token_revoked", _fake_revoked)
    monkeypatch.setattr(auth_deps, "is_user_blacklisted", _fake_user_blacklisted)


def _make_app(resolver: _FakeResolver) -> FastAPI:
    """最小 app：一个受保护端点 + 一个可选认证端点。"""
    app = FastAPI()
    app.add_exception_handler(PasswordChangeRequiredError, create_error_handler(403, "强制改密"))
    app.add_exception_handler(BaseAPIError, global_exception_handler)

    @app.get("/api/v1/ping")
    async def ping(user: dict = Depends(get_current_user)):
        return {"ok": True, "user_id": user["id"]}

    @app.get("/api/v1/public")
    async def public(user: dict | None = Depends(get_current_user_optional)):
        return {"user_id": user["id"] if user else None}

    app.dependency_overrides[get_user_status_resolver] = lambda: resolver
    return app


async def _create_token(user_id: int = 42) -> str:
    access, _ = await AuthService.create_token_pair(
        user_id=user_id, username="u", email="u@t.com", role_code="viewer",
    )
    return access


# ==================== 1. P0：改密链路不经 UserUpdate ====================


async def _seed_user(tmp_db, username: str, password: str, must_change: bool = False):
    from sqlalchemy import func, select

    from novamind.core.auth.hashing import get_password_hash_async
    from novamind.features.user.models.role import Role
    from novamind.features.user.models.user import User, UserStatus

    # SQLite 下 BigInteger 主键不自增，手动分配 ID
    next_id = (await tmp_db.execute(select(func.max(Role.id)))).scalar() or 0
    role = Role(id=next_id + 1, code=f"r_{username}", name=username, is_system=False)
    tmp_db.add(role)
    await tmp_db.flush()

    next_uid = (await tmp_db.execute(select(func.max(User.id)))).scalar() or 0
    user = User(
        id=next_uid + 1,
        username=username,
        email=f"{username}@t.com",
        password_hash=await get_password_hash_async(password),
        role_id=role.id,
        status=UserStatus.ACTIVE,
        must_change_password=must_change,
    )
    tmp_db.add(user)
    await tmp_db.flush()
    return user


@pytest.mark.asyncio
async def test_change_password_writes_hash_directly(tmp_db, monkeypatch):
    """change_password 直写哈希——原实现 UserUpdate(password=97字符哈希) 必抛 ValidationError。"""
    from novamind.core.auth.hashing import verify_password_async
    from novamind.features.user.models.user import User
    from novamind.features.user.repository.user_repository import UserRepository
    from novamind.features.user.services.user_service import UserService

    user = await _seed_user(tmp_db, "u1", "Old@1234")

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(AuthService, "blacklist_all_user_tokens", _noop)

    svc = UserService(UserRepository(tmp_db))
    assert await svc.change_password(user.id, "Old@1234", "New@12345") is True

    refreshed = await tmp_db.get(User, user.id)
    assert await verify_password_async("New@12345", refreshed.password_hash)
    assert refreshed.must_change_password is False


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_old_password(tmp_db):
    from novamind.features.user.repository.user_repository import UserRepository
    from novamind.features.user.services.user_service import UserService

    user = await _seed_user(tmp_db, "u1b", "Old@1234")

    svc = UserService(UserRepository(tmp_db))
    with pytest.raises(Exception) as exc_info:
        await svc.change_password(user.id, "Wrong@123", "New@12345")
    assert "当前密码错误" in str(exc_info.value)


@pytest.mark.asyncio
async def test_admin_reset_password_roundtrip(tmp_db, monkeypatch):
    """admin_reset_password 返回的临时密码可验证且设置强制改密标记。"""
    from novamind.core.auth.hashing import verify_password_async
    from novamind.features.user.models.user import User
    from novamind.features.user.repository.user_repository import UserRepository
    from novamind.features.user.services.user_service import UserService

    user = await _seed_user(tmp_db, "u2", "Old@1234")

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(AuthService, "blacklist_all_user_tokens", _noop)

    svc = UserService(UserRepository(tmp_db))
    temp_password, uid = await svc.admin_reset_password(user.id)
    assert uid == user.id

    refreshed = await tmp_db.get(User, user.id)
    assert await verify_password_async(temp_password, refreshed.password_hash)
    assert refreshed.must_change_password is True


# ==================== 2. P1：认证链 token 级黑名单 ====================


@pytest.mark.asyncio
async def test_revoked_jti_rejected_at_auth_chain(monkeypatch):
    """登出后（jti 进 token 级黑名单），同一 access token 请求被 401 拒绝。"""
    _patch_blacklists(monkeypatch, revoked=True)

    app = _make_app(_FakeResolver())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _create_token()
        resp = await client.get("/api/v1/ping", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_active_jti_passes(monkeypatch):
    """未撤销的 jti 正常通过（回归：黑名单检查不应误伤正常 token）。"""
    _patch_blacklists(monkeypatch, revoked=False)

    app = _make_app(_FakeResolver())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _create_token(user_id=42)
        resp = await client.get("/api/v1/ping", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == 42


# ==================== 3. P2：强制改密服务端门禁 ====================


@pytest.mark.asyncio
async def test_must_change_password_blocks_non_exempt_endpoint(monkeypatch):
    """must_change_password 用户访问普通端点 → 403 PASSWORD_CHANGE_REQUIRED。"""
    _patch_blacklists(monkeypatch, revoked=False)

    app = _make_app(_FakeResolver(must_change_password=True))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _create_token(user_id=7)
        resp = await client.get("/api/v1/ping", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


@pytest.mark.asyncio
async def test_must_change_password_allows_exempt_endpoint(monkeypatch):
    """must_change_password 用户访问豁免路径前缀（改密/登出/自身信息）→ 放行。"""
    _patch_blacklists(monkeypatch, revoked=False)

    app = _make_app(_FakeResolver(must_change_password=True))

    @app.post("/api/v1/user/users/me/change-password")
    async def change_pw(user: dict = Depends(get_current_user)):
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _create_token(user_id=7)
        resp = await client.post(
            "/api/v1/user/users/me/change-password",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_must_change_password_not_enforced_for_optional_auth(monkeypatch):
    """可选认证不执行强制改密门禁（公开端点不因改密状态 403）。"""
    _patch_blacklists(monkeypatch, revoked=False)

    app = _make_app(_FakeResolver(must_change_password=True))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _create_token(user_id=7)
        resp = await client.get("/api/v1/public", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == 7


# ==================== 4. RBAC 缓存失效 ====================


class _RecordingChecker(PermissionCheckerPort):
    def __init__(self):
        self.invalidated: list[int] = []

    async def get_user_permissions(self, user_id: int) -> set[str]:
        return set()

    async def invalidate(self, user_id: int) -> None:
        self.invalidated.append(user_id)


@pytest.mark.asyncio
async def test_update_role_invalidates_role_users_cache(tmp_db):
    """角色权限变更后，该角色下所有用户的权限缓存被失效。"""
    from sqlalchemy import func, select

    from novamind.features.user.models.role import Permission, Role
    from novamind.features.user.models.user import User, UserStatus
    from novamind.features.user.services.role_service import RoleService

    # 预置权限码（set_role_permissions 校验 code 必须存在）；SQLite 手动分配 ID
    next_perm_id = (await tmp_db.execute(select(func.max(Permission.id)))).scalar() or 0
    perm = Permission(id=next_perm_id + 1, code="user.manage", name="用户管理", module="user")
    tmp_db.add(perm)
    next_role_id = (await tmp_db.execute(select(func.max(Role.id)))).scalar() or 0
    role = Role(id=next_role_id + 1, code="auditor", name="审计", is_system=False)
    tmp_db.add(role)
    await tmp_db.flush()

    users = []
    next_uid = (await tmp_db.execute(select(func.max(User.id)))).scalar() or 0
    for i in range(3):
        u = User(id=next_uid + i + 1, username=f"aud{i}", email=f"aud{i}@t.com", password_hash="x",
                 role_id=role.id, status=UserStatus.ACTIVE)
        tmp_db.add(u)
        users.append(u)
    await tmp_db.flush()

    checker = _RecordingChecker()
    svc = RoleService(tmp_db, checker)
    await svc.update_role(role.id, permission_codes=["user.manage"])

    assert sorted(checker.invalidated) == sorted(u.id for u in users)
