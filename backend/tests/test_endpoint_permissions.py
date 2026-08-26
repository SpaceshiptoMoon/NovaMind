"""现有 require_admin 端点改 require_permission 后，真实 router 权限映射验证。

用 FastAPI TestClient 挂载真实的 user_router / skill_router，通过
``dependency_overrides`` 注入假用户、假权限检查器和假服务，验证各端点的
RBAC 映射与鉴权依赖。
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novamind.core.auth.dependencies import get_current_user
from novamind.core.authorization.dependencies import (
    require_permission,
    get_permission_checker_dep,
)
from novamind.core.authorization.exceptions import PermissionDeniedError
from novamind.core.authorization.ports import PermissionCheckerPort
from novamind.core.middleware.base_exception_handler import create_error_handler
from novamind.core.middleware.manifest import API_V1_PREFIX
from novamind.features.user.api.user_routes import router as user_router
from novamind.features.user.api.dependencies import get_user_service
from novamind.features.skill.api.routes import router as skill_router
from novamind.features.skill.api import routes as skill_routes_module
from novamind.features.skill.api.dependencies import (
    get_skill_service,
    get_llm_review_settings,
    update_llm_review_settings,
)


USER_PREFIX = f"{API_V1_PREFIX}/user"
SKILL_PREFIX = f"{API_V1_PREFIX}/skills"


class _FakeChecker(PermissionCheckerPort):
    """测试用权限检查器：返回固定权限集合。"""

    def __init__(self, permissions: set[str]) -> None:
        self.permissions = set(permissions)

    async def get_user_permissions(self, user_id: int) -> set[str]:
        return set(self.permissions)

    async def invalidate(self, user_id: int) -> None:
        pass


class _FakeUserService:
    """用户服务假实现：避免单元测试命中真实数据库。"""

    async def get_users(self, skip: int, limit: int) -> list:
        return []


class _FakeSkillMarketplaceService:
    """技能广场服务假实现。"""

    db = None

    async def list_pending_review(self, limit: int, offset: int) -> tuple:
        return ([], 0)

    async def approve_skill(self, skill_id: int):
        return SimpleNamespace(review_status=1)


async def _fake_skill_service():
    """技能服务依赖覆盖：使用假实现。"""
    yield _FakeSkillMarketplaceService()


async def _fake_update_llm_review_settings(enabled: bool, model: str | None = None) -> None:
    pass


async def _fake_batch_usernames(db, user_ids: list[int]) -> dict:
    """替换 _batch_get_usernames，避免列表查询走真实数据库。"""
    return {}


def _make_app(
    permissions: set[str],
    role_code: str = "editor",
    *,
    override_current_user: bool = True,
) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(
        PermissionDeniedError, create_error_handler(403, "权限不足")
    )

    if override_current_user:
        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "role_code": role_code,
        }
    app.dependency_overrides[get_permission_checker_dep] = lambda: _FakeChecker(
        permissions
    )
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService()
    app.dependency_overrides[get_skill_service] = _fake_skill_service
    app.dependency_overrides[get_llm_review_settings] = lambda: {
        "llm_review_enabled": False,
        "llm_review_model": None,
    }
    app.dependency_overrides[update_llm_review_settings] = _fake_update_llm_review_settings

    app.include_router(user_router, prefix=USER_PREFIX)
    app.include_router(skill_router, prefix=SKILL_PREFIX)
    return app


# ==================== 用户管理端点 ====================


def test_get_users_denied_without_permission():
    client = TestClient(_make_app(set()))
    resp = client.get(f"{USER_PREFIX}/users")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


def test_get_users_allowed_with_user_manage():
    client = TestClient(_make_app({"user.manage"}))
    resp = client.get(f"{USER_PREFIX}/users")
    assert resp.status_code == 200


def test_get_users_admin_bypass_without_permission():
    client = TestClient(_make_app(set(), role_code="admin"))
    resp = client.get(f"{USER_PREFIX}/users")
    assert resp.status_code == 200


# ==================== 技能广场管理员端点 ====================


@pytest.fixture
def patched_batch_usernames(monkeypatch):
    """避免待审核列表查询真实用户表。"""
    monkeypatch.setattr(
        skill_routes_module, "_batch_get_usernames", _fake_batch_usernames
    )


def test_get_skills_admin_reviews_denied_without_permission(patched_batch_usernames):
    client = TestClient(_make_app(set()))
    resp = client.get(f"{SKILL_PREFIX}/admin/reviews")
    assert resp.status_code == 403


def test_get_skills_admin_reviews_denied_with_only_skill_review(
    patched_batch_usernames,
):
    client = TestClient(_make_app({"skill.review"}))
    resp = client.get(f"{SKILL_PREFIX}/admin/reviews")
    assert resp.status_code == 403


def test_get_skills_admin_reviews_allowed_with_skill_config(
    patched_batch_usernames,
):
    client = TestClient(_make_app({"skill.config"}))
    resp = client.get(f"{SKILL_PREFIX}/admin/reviews")
    assert resp.status_code == 200


def test_post_skills_admin_reviews_approve_denied_with_only_skill_config():
    client = TestClient(_make_app({"skill.config"}))
    resp = client.post(f"{SKILL_PREFIX}/admin/reviews/1/approve")
    assert resp.status_code == 403


def test_post_skills_admin_reviews_approve_allowed_with_skill_review():
    client = TestClient(_make_app({"skill.review"}))
    resp = client.post(f"{SKILL_PREFIX}/admin/reviews/1/approve")
    assert resp.status_code == 200
    assert resp.json()["review_status"] == 1


# ==================== skills/validate 鉴权修补 ====================


def test_post_skills_validate_allowed_for_active_user():
    client = TestClient(_make_app({"skill.config"}))
    resp = client.post(
        f"{SKILL_PREFIX}/validate",
        json={
            "content": "---\nname: test-skill\ndescription: A test skill\n---\nBody\n"
        },
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_post_skills_validate_requires_authentication():
    client = TestClient(_make_app(set(), override_current_user=False))
    resp = client.post(
        f"{SKILL_PREFIX}/validate",
        json={
            "content": "---\nname: test-skill\ndescription: A test skill\n---\nBody\n"
        },
    )
    assert resp.status_code == 401
