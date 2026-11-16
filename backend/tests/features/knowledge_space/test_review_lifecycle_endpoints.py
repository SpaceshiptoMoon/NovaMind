"""复审闭环与生命周期手动动作端点回归（运营飞轮回补 2026-11-16）。

覆盖：
1. 复审状态读取 / 确认顺延（owner 与 admin 放行、viewer 拒 403、文档不存在 404）；
2. 复审周期设置（清周期 = None 透传）；
3. 生命周期 archive/reactivate（成功 / 非法转换 409 / 不存在 404 / 权限 403）。

正反两用例原则：每个权限档与错误档配一个相邻正常场景对照。
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from novamind.core.middleware.base_exception_handler import register_module_exceptions
from novamind.features.knowledge_space.api.dependencies import (
    get_current_user_id,
    get_document_query_service,
    get_document_review_service,
    get_lifecycle_service,
    validate_space_member,
)
from novamind.features.knowledge_space.api.document_routes import router as doc_router
from novamind.features.knowledge_space.exceptions import (
    DocumentLifecycleTransitionError,
    DocumentNotFoundError,
    SpaceAccessDeniedError,
)
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.space_member import SpaceRole
from novamind.features.knowledge_space.services.lifecycle_service import (
    DocumentLifecycleError,
)

pytestmark = pytest.mark.unit

API = "/api/v1/spaces/1/knowledge-bases/2/documents/9"

USER_ID = 7  # 同时是文档 owner


def _doc(**overrides) -> Document:
    fields = dict(
        id=9, space_id=1, kb_id=2, filename="报销制度.docx", uploader_id=USER_ID,
        owner_id=USER_ID, lifecycle_status="active",
        review_cycle_days=None, next_review_at=None,
    )
    fields.update(overrides)
    return Document(**fields)


def _member(role: SpaceRole):
    return SimpleNamespace(role=role, space_id=1, user_id=USER_ID)


def _make_app(
    *,
    document=None,
    role: SpaceRole = SpaceRole.VIEWER,
    confirm_mock=None,
    settings_mock=None,
    archive_mock=None,
    reactivate_mock=None,
) -> tuple[FastAPI, dict]:
    """构造四依赖全 mock 的最小应用（document=None 模拟 404）。"""
    app = FastAPI()
    app.include_router(doc_router, prefix="/api/v1/spaces/{space_id}/knowledge-bases")
    # 裸 FastAPI 不带模块异常处理器——手动注册被测异常类（create_app 内由 startup 挂）
    register_module_exceptions(app, status_map={
        SpaceAccessDeniedError: 403,
        DocumentNotFoundError: 404,
        DocumentLifecycleTransitionError: 409,
    })

    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[validate_space_member] = lambda: _member(role)
    app.dependency_overrides[get_document_query_service] = lambda: SimpleNamespace(
        get_document=AsyncMock(return_value=document)
    )
    review_service = SimpleNamespace(
        confirm_review=confirm_mock or AsyncMock(
            return_value=__import__("datetime").datetime(2027, 1, 1)
        ),
        update_settings=settings_mock or AsyncMock(return_value=None),
    )
    app.dependency_overrides[get_document_review_service] = lambda: review_service
    lifecycle_service = SimpleNamespace(
        archive=archive_mock or AsyncMock(return_value=_doc(lifecycle_status="archived")),
        reactivate=reactivate_mock
        or AsyncMock(return_value=_doc(lifecycle_status="active")),
    )
    app.dependency_overrides[get_lifecycle_service] = lambda: lifecycle_service
    return app, {
        "review": review_service,
        "lifecycle": lifecycle_service,
    }


def test_get_review_status_member_readable():
    """复审状态读取：viewer 成员可读（对照：处置才要求 admin/owner）。"""
    app, _ = _make_app(document=_doc(review_cycle_days=30), role=SpaceRole.VIEWER)
    with TestClient(app) as client:
        resp = client.get(f"{API}/review")
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_cycle_days"] == 30
    assert body["fallback_cycle_days"] > 0


def test_confirm_review_owner_ok_and_service_called():
    """确认复审：文档 owner 放行，顺延值透传（正例）。"""
    confirm = AsyncMock(return_value=__import__("datetime").datetime(2027, 2, 1))
    app, mocks = _make_app(document=_doc(), role=SpaceRole.VIEWER, confirm_mock=confirm)
    with TestClient(app) as client:
        resp = client.post(f"{API}/review/confirm")
    assert resp.status_code == 200
    assert resp.json()["next_review_at"].startswith("2027-02-01")
    mocks["review"].confirm_review.assert_awaited_once()


def test_confirm_review_admin_ok():
    """确认复审：空间管理员放行（非 owner 也可，运营处置位）。"""
    app, _ = _make_app(
        document=_doc(owner_id=999), role=SpaceRole.ADMIN
    )
    with TestClient(app) as client:
        resp = client.post(f"{API}/review/confirm")
    assert resp.status_code == 200


def test_confirm_review_viewer_not_owner_forbidden():
    """确认复审：viewer 且非 owner 拒 403（反例）。"""
    app, _ = _make_app(document=_doc(owner_id=999), role=SpaceRole.VIEWER)
    with TestClient(app) as client:
        resp = client.post(f"{API}/review/confirm")
    assert resp.status_code == 403


def test_confirm_review_doc_missing_404():
    """确认复审：文档不存在 404（反例）。"""
    app, _ = _make_app(document=None)
    with TestClient(app) as client:
        resp = client.post(f"{API}/review/confirm")
    assert resp.status_code == 404


def test_update_review_settings_none_passthrough():
    """设置周期：None（清除）透传到服务层（对照：数值经 schema 校验）。"""
    settings = AsyncMock(return_value=None)
    app, mocks = _make_app(document=_doc(), role=SpaceRole.ADMIN, settings_mock=settings)
    with TestClient(app) as client:
        resp = client.put(f"{API}/review", json={"review_cycle_days": None})
    assert resp.status_code == 200
    mocks["review"].update_settings.assert_awaited_once()
    # pydantic 调用位置参数即可，断言第一参为 None
    assert mocks["review"].update_settings.await_args.args[1] is None


def test_update_review_settings_invalid_value_422():
    """设置周期：非法值（0）被 schema 拒 422（反例）。"""
    app, _ = _make_app(document=_doc(), role=SpaceRole.ADMIN)
    with TestClient(app) as client:
        resp = client.put(f"{API}/review", json={"review_cycle_days": 0})
    assert resp.status_code == 422


def test_lifecycle_archive_ok():
    """生命周期归档：admin 放行，动作后的状态透传（正例）。"""
    app, mocks = _make_app(document=_doc(), role=SpaceRole.ADMIN)
    with TestClient(app) as client:
        resp = client.post(f"{API}/lifecycle", json={"action": "archive"})
    assert resp.status_code == 200
    assert resp.json()["lifecycle_status"] == "archived"
    mocks["lifecycle"].archive.assert_awaited_once_with(9)


def test_lifecycle_reactivate_ok():
    """生命周期恢复：owner 放行（正例）。"""
    app, _ = _make_app(document=_doc(), role=SpaceRole.VIEWER)
    with TestClient(app) as client:
        resp = client.post(f"{API}/lifecycle", json={"action": "reactivate"})
    assert resp.status_code == 200
    assert resp.json()["lifecycle_status"] == "active"


def test_lifecycle_invalid_transition_409():
    """生命周期：状态机拒绝（如 archived → archived）转 409（反例）。"""
    archive = AsyncMock(side_effect=DocumentLifecycleError("非法转换"))
    app, _ = _make_app(
        document=_doc(lifecycle_status="archived"), role=SpaceRole.ADMIN, archive_mock=archive
    )
    with TestClient(app) as client:
        resp = client.post(f"{API}/lifecycle", json={"action": "archive"})
    assert resp.status_code == 409


def test_lifecycle_doc_missing_404():
    """生命周期：文档不存在（ValueError）转 404（反例）。"""
    archive = AsyncMock(side_effect=ValueError("不存在"))
    app, _ = _make_app(document=None, role=SpaceRole.ADMIN, archive_mock=archive)
    with TestClient(app) as client:
        resp = client.post(f"{API}/lifecycle", json={"action": "archive"})
    assert resp.status_code == 404


def test_lifecycle_viewer_not_owner_forbidden():
    """生命周期：viewer 且非 owner 拒 403（反例）。"""
    app, _ = _make_app(document=_doc(owner_id=999), role=SpaceRole.VIEWER)
    with TestClient(app) as client:
        resp = client.post(f"{API}/lifecycle", json={"action": "archive"})
    assert resp.status_code == 403
