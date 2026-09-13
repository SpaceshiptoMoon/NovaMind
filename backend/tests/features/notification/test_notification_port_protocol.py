"""NotificationPort 端口与 adapter 回归测试。"""
from types import SimpleNamespace

import pytest

from novamind.shared.notification_ports import NotificationPort
from novamind.features.notification.adapters.notification_port_adapter import (
    HostNotificationPort,
    as_notification_port,
)


@pytest.mark.unit
def test_host_port_satisfies_protocol():
    """HostNotificationPort 满足 NotificationPort 协议（runtime_checkable）"""
    assert isinstance(HostNotificationPort(), NotificationPort)
    assert isinstance(as_notification_port(), NotificationPort)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_with_session_uses_caller_db(monkeypatch):
    """传 db 时复用调用方会话构造 NotificationService"""
    captured = {}

    class _FakeService:
        def __init__(self, db):
            captured["db"] = db

        async def send_notification(self, **kwargs):
            captured.update(kwargs)

    import novamind.features.notification.adapters.notification_port_adapter as mod
    monkeypatch.setattr(
        "novamind.features.notification.services.notification_service.NotificationService",
        _FakeService,
    )
    # 防御：确认 patch 到位（延迟 import 走的是 service 模块属性）
    assert mod is not None

    fake_db = SimpleNamespace()
    port = as_notification_port(fake_db)
    await port.send(user_id=1, type="skill_review", title="t", content="c")

    assert captured["db"] is fake_db
    assert captured["user_id"] == 1
    assert captured["type"] == "skill_review"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_without_session_opens_independent_session(monkeypatch):
    """db=None 时经 get_db_session 开独立短会话"""
    captured = {}
    fake_session = SimpleNamespace()

    class _FakeSessionFactoryCtx:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, *args):
            return False

    def _fake_get_db_session():
        captured["session_factory_called"] = True
        return _FakeSessionFactoryCtx()

    class _FakeService:
        def __init__(self, db):
            captured["db"] = db

        async def send_notification(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "novamind.features.notification.services.notification_service.NotificationService",
        _FakeService,
    )
    import novamind.features.notification.adapters.notification_port_adapter as mod
    monkeypatch.setattr(mod, "get_db_session", _fake_get_db_session)

    port = as_notification_port(None)
    await port.send(user_id=2, type="document_ready", title="t", content="c")

    assert captured.get("session_factory_called") is True
    assert captured["db"] is fake_session


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_swallows_exceptions(monkeypatch):
    """发送异常被吞（记日志），不向调用方抛——通知不打断主业务流程"""
    class _BoomService:
        def __init__(self, db):
            pass

        async def send_notification(self, **kwargs):
            raise RuntimeError("DB down")

    monkeypatch.setattr(
        "novamind.features.notification.services.notification_service.NotificationService",
        _BoomService,
    )

    port = as_notification_port(SimpleNamespace())
    await port.send(user_id=1, type="system", title="t", content="c")  # 不抛
