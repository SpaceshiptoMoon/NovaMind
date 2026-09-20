"""通知 WS 端点回归测试。

覆盖：合法 token 连接 → ping/pong、注册进 manager；无效 token → close 4401；
断连后注册表清空。认证用 monkeypatch ws_authenticate（避免造真实 JWT +
UserStatusResolver 装配链），close code 契约保持真实。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from novamind.core.auth import get_user_status_resolver
from novamind.core.ws.connection_manager import manager as ws_manager
from novamind.features.notification.api.routes import router as notification_router

pytestmark = pytest.mark.unit

_FAKE_USER = {"id": 7, "username": "alice", "email": "a@b.c", "is_admin": False}


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(notification_router, prefix="/api/v1/notifications")
    # resolver 依赖在依赖解析阶段就要实例化（早于 ws_authenticate 被 patch），
    # 用假 resolver 覆盖跳过真实装配
    app.dependency_overrides[get_user_status_resolver] = lambda: object()
    return app


@pytest.fixture(autouse=True)
def _clean_manager():
    """用例间清空共享 manager 注册表"""
    ws_manager._connections.clear()
    yield
    ws_manager._connections.clear()


@pytest.fixture
def client_with_auth(monkeypatch):
    """合法认证：ws_authenticate 返回假用户"""

    async def _ok(websocket, resolver):
        return dict(_FAKE_USER), None

    monkeypatch.setattr(
        "novamind.features.notification.api.routes.ws_authenticate", _ok,
    )
    # resolver 依赖照常解析（不会被触达，因为 ws_authenticate 已被换）
    app = _make_app()
    return TestClient(app)


@pytest.fixture
def client_unauthenticated(monkeypatch):
    """认证失败：close 4401"""

    async def _deny(websocket, resolver):
        return None, 4401

    monkeypatch.setattr(
        "novamind.features.notification.api.routes.ws_authenticate", _deny,
    )
    app = _make_app()
    return TestClient(app)


@pytest.mark.unit
def test_ws_ping_pong_and_registration(client_with_auth):
    """合法连接注册进 manager；ping 收到 pong；断连后注册表清空"""
    with client_with_auth.websocket_connect("/api/v1/notifications/ws") as ws:
        assert ws_manager.connections_count(7) == 1, "连接应注册进 manager"
        ws.send_json({"action": "ping"})
        reply = ws.receive_json()
        assert reply == {"type": "pong", "data": {}}
    assert ws_manager.connections_count(7) == 0, "断连后应从注册表摘除"


@pytest.mark.unit
def test_ws_unauthenticated_close_4401(client_unauthenticated):
    """无效 token：accept 后 close 4401，且不注册进 manager"""
    with pytest.raises(Exception):
        with client_unauthenticated.websocket_connect("/api/v1/notifications/ws") as ws:
            ws.receive_json()
    assert ws_manager.connections_count(7) == 0


@pytest.mark.unit
def test_ws_multi_tab_multiple_connections(client_with_auth):
    """同一用户两个连接（模拟双标签页）都注册"""
    with client_with_auth.websocket_connect("/api/v1/notifications/ws") as ws1:
        with client_with_auth.websocket_connect("/api/v1/notifications/ws") as ws2:
            assert ws_manager.connections_count(7) == 2
            ws1.send_json({"action": "ping"})
            assert ws1.receive_json() == {"type": "pong", "data": {}}
            ws2.send_json({"action": "ping"})
            assert ws2.receive_json() == {"type": "pong", "data": {}}
        assert ws_manager.connections_count(7) == 1
    assert ws_manager.connections_count(7) == 0
