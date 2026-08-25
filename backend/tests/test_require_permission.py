"""require_permission 依赖测试（用 FastAPI TestClient + 依赖覆盖）。"""

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from novamind.core.authorization.dependencies import require_permission, get_permission_checker_dep
from novamind.core.auth.dependencies import get_current_user
from novamind.core.authorization.ports import PermissionCheckerPort


class FakeChecker(PermissionCheckerPort):
    """测试用权限检查器，仅返回固定权限集合。"""

    def __init__(self, permissions: set[str]) -> None:
        self.permissions = set(permissions)

    async def get_user_permissions(self, user_id: int) -> set[str]:
        return set(self.permissions)

    async def invalidate(self, user_id: int) -> None:
        pass


def _make_app(user: dict):
    """构造带 require_permission 守卫的测试应用，注入假用户与假权限检查器。"""
    app = FastAPI()

    # 注入假用户
    app.dependency_overrides[get_current_user] = lambda: user
    # 注入假权限检查器（按用户声明的 permissions 返回）
    app.dependency_overrides[get_permission_checker_dep] = lambda: FakeChecker(
        set(user.get("permissions", []))
    )

    @app.get("/secure", dependencies=[Depends(require_permission("user.manage"))])
    def secure():
        return {"ok": True}

    return app


def test_admin_without_permission_passes():
    """admin 角色无需显式权限即可放行。"""
    app = _make_app({"id": 1, "role_code": "admin", "permissions": []})
    client = TestClient(app)
    resp = client.get("/secure")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_user_with_permission_passes():
    """拥有对应权限码的普通用户放行。"""
    app = _make_app({"id": 2, "role_code": "editor", "permissions": ["user.manage"]})
    client = TestClient(app)
    resp = client.get("/secure")
    assert resp.status_code == 200


def test_user_without_permission_denied():
    """缺少权限码的普通用户返回 403。"""
    app = _make_app({"id": 3, "role_code": "viewer", "permissions": []})
    client = TestClient(app)
    resp = client.get("/secure")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "缺少权限: user.manage"


def test_checker_dep_not_implemented_by_default():
    """未装配 get_permission_checker_dep 时，依赖调用应抛出 NotImplementedError。"""
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role_code": "editor"}

    @app.get("/secure", dependencies=[Depends(require_permission("user.manage"))])
    def secure():
        return {"ok": True}

    client = TestClient(app)
    with pytest.raises(NotImplementedError):
        client.get("/secure")
