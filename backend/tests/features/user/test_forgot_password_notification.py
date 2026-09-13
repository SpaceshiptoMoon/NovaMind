"""forgot_password 站内通知回归测试。

批次 6 接线的回归保护：
1. 邮箱存在 → 发 password_reset 站内通知（link=None）；
2. 防枚举语义不变：邮箱不存在 / 内部异常时响应恒 200 成功。
"""
import pytest
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novamind.features.user.api import user_routes


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(user_routes.router)
    return app


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """PASSWORD_RESET 是 3/hour：用例间清空 limiter 状态，避免 429 串扰"""
    from novamind.core.middleware.rate_limit import get_limiter
    get_limiter().reset()
    yield
    get_limiter().reset()


@pytest.fixture
def capture(monkeypatch):
    """patch 掉外部依赖：get_db_session / EmailService / as_notification_port"""
    state = {
        "user": None,  # get_user_by_email 的返回值
        "port_calls": [],
        "email_calls": [],
        "port_boom": False,
    }

    fake_user = SimpleNamespace(id=66, username="alice", email="alice@example.com")

    class _FakeDBCtx:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, *args):
            return False

    class _FakeRepo:
        def __init__(self, db):
            pass

        async def get_user_by_email(self, email, use_cache=False):
            return state["user"]

    class _FakeAuthService:
        @classmethod
        async def generate_reset_token(cls, user_id):
            return f"token-for-{user_id}"

    class _FakeEmail:
        @staticmethod
        async def send_reset_email(to_email, reset_link, username=""):
            state["email_calls"].append((to_email, reset_link))

    class _FakePort:
        async def send(self, **kwargs):
            if state["port_boom"]:
                raise RuntimeError("notify down")
            state["port_calls"].append(kwargs)

    monkeypatch.setattr(
        "novamind.core.database.database.get_db_session", lambda: _FakeDBCtx(),
    )
    monkeypatch.setattr(
        "novamind.features.user.repository.user_repository.UserRepository", _FakeRepo,
    )
    monkeypatch.setattr(user_routes, "AuthService", _FakeAuthService)
    monkeypatch.setattr(
        "novamind.features.notification.services.email_service.EmailService", _FakeEmail,
    )
    monkeypatch.setattr(
        "novamind.features.notification.adapters.notification_port_adapter.as_notification_port",
        lambda db: _FakePort(),
    )
    state["fake_user"] = fake_user
    return state


@pytest.mark.unit
def test_forgot_password_sends_in_app_notification(capture):
    """邮箱存在：发站内通知（type=password_reset, link=None），响应 200"""
    capture["user"] = capture["fake_user"]
    client = TestClient(_make_app())
    resp = client.post(
        "/auth/forgot-password", json={"email": "alice@example.com"},
    )

    assert resp.status_code == 200
    assert "重置" in resp.json()["message"]
    assert len(capture["port_calls"]) == 1
    call = capture["port_calls"][0]
    assert call["user_id"] == 66
    assert call["type"] == "password_reset"
    assert call.get("link") is None
    assert "重置" in call["title"]
    # 邮件链路保持不变
    assert len(capture["email_calls"]) == 1


@pytest.mark.unit
def test_forgot_password_unknown_email_no_notification(capture):
    """邮箱不存在：不发通知，响应仍 200 成功（防枚举）"""
    capture["user"] = None
    client = TestClient(_make_app())
    resp = client.post(
        "/auth/forgot-password", json={"email": "ghost@example.com"},
    )

    assert resp.status_code == 200
    assert "已注册" in resp.json()["message"]
    assert capture["port_calls"] == []
    assert capture["email_calls"] == []


@pytest.mark.unit
def test_forgot_password_notification_failure_still_success(capture):
    """通知发送异常被吞：响应不变，主流程（邮件）不受影响"""
    capture["user"] = capture["fake_user"]
    capture["port_boom"] = True
    client = TestClient(_make_app())
    resp = client.post(
        "/auth/forgot-password", json={"email": "alice@example.com"},
    )

    assert resp.status_code == 200
    assert len(capture["email_calls"]) == 1, "邮件链路不受通知失败影响"
