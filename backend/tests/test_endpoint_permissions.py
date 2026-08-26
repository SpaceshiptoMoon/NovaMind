"""现有 require_admin 端点改 require_permission 后行为等价（用 TestClient 覆盖依赖）。"""

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from novamind.core.auth.dependencies import get_current_user
from novamind.core.authorization.dependencies import (
    require_permission,
    get_permission_checker_dep,
)
from novamind.core.authorization.exceptions import PermissionDeniedError
from novamind.core.authorization.ports import PermissionCheckerPort
from novamind.core.middleware.base_exception_handler import create_error_handler


class _FakeChecker(PermissionCheckerPort):
    """测试用权限检查器：返回固定权限集合。"""

    def __init__(self, permissions: set[str]) -> None:
        self.permissions = set(permissions)

    async def get_user_permissions(self, user_id: int) -> set[str]:
        return set(self.permissions)

    async def invalidate(self, user_id: int) -> None:
        pass


def _make_app(permissions: set[str], role_code: str = "editor") -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "role_code": role_code,
    }
    app.dependency_overrides[get_permission_checker_dep] = lambda: _FakeChecker(
        permissions
    )
    app.add_exception_handler(
        PermissionDeniedError, create_error_handler(403, "权限不足")
    )

    @app.delete("/users/1", dependencies=[Depends(require_permission("user.manage"))])
    def del_user():
        return {"ok": True}

    @app.get("/skills/admin/settings", dependencies=[Depends(require_permission("skill.config"))])
    def get_skill_settings():
        return {"ok": True}

    @app.post(
        "/skills/admin/reviews/1/approve",
        dependencies=[Depends(require_permission("skill.review"))],
    )
    def approve_skill():
        return {"ok": True}

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


def test_skill_config_allowed_with_permission():
    client = TestClient(_make_app({"skill.config"}))
    assert client.get("/skills/admin/settings").status_code == 200


def test_skill_config_denied_without_permission():
    client = TestClient(_make_app(set()))
    assert client.get("/skills/admin/settings").status_code == 403


def test_skill_review_allowed_with_permission():
    client = TestClient(_make_app({"skill.review"}))
    assert client.post("/skills/admin/reviews/1/approve").status_code == 200


def test_skill_review_denied_without_permission():
    client = TestClient(_make_app(set()))
    assert client.post("/skills/admin/reviews/1/approve").status_code == 403
