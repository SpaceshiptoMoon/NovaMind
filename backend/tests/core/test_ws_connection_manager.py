"""ConnectionManager 回归测试。

通知常驻订阅通道的 per-user 连接注册表：多连接注册/摘除、全连接推送、
单连接异常摘除、无连接零开销、datetime 事件经 dumps_event 兜底。
"""
import datetime

import pytest
from novamind.core.ws.connection_manager import ConnectionManager
from novamind.core.ws.stream import envelope

pytestmark = pytest.mark.unit


class FakeWebSocket:
    """记录 send_text 调用的桩 WebSocket；可注入发送异常。"""

    def __init__(self, fail: bool = False):
        self.sent: list[str] = []
        self.fail = fail

    async def send_text(self, payload: str) -> None:
        if self.fail:
            raise RuntimeError("connection closed")
        self.sent.append(payload)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connect_disconnect_registry_lifecycle():
    """注册/摘除连接，最后一个连接移除后清掉空集合"""
    mgr = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()

    await mgr.connect(1, ws1)
    await mgr.connect(1, ws2)
    assert mgr.connections_count(1) == 2

    await mgr.disconnect(1, ws1)
    assert mgr.connections_count(1) == 1

    await mgr.disconnect(1, ws2)
    assert mgr.connections_count(1) == 0
    assert 1 not in mgr._connections, "空集合应被清理"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disconnect_unknown_user_noop():
    """摘除未注册用户/连接是安全 no-op"""
    mgr = ConnectionManager()
    ws = FakeWebSocket()
    await mgr.disconnect(999, ws)  # 不抛
    await mgr.connect(1, ws)
    await mgr.disconnect(1, FakeWebSocket())  # 摘别的连接不影响已注册的
    assert mgr.connections_count(1) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_to_user_reaches_all_connections():
    """同一用户多连接（多标签页）全达"""
    mgr = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await mgr.connect(1, ws1)
    await mgr.connect(1, ws2)

    event = envelope("notification.new", {"id": 7, "title": "t"})
    delivered = await mgr.send_to_user(1, event)

    assert delivered is True
    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1
    assert ws1.sent[0] == ws2.sent[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_to_user_no_connections_returns_false():
    """无连接直接返回 False，零开销"""
    mgr = ConnectionManager()
    assert await mgr.send_to_user(42, {"type": "x", "data": {}}) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_to_user_drops_failed_connection():
    """单连接发送异常被摘除，其余连接照常收到"""
    mgr = ConnectionManager()
    bad, good = FakeWebSocket(fail=True), FakeWebSocket()
    await mgr.connect(1, bad)
    await mgr.connect(1, good)

    delivered = await mgr.send_to_user(1, envelope("notification.new", {"id": 1}))

    assert delivered is True
    assert mgr.connections_count(1) == 1, "失败连接应被摘除"
    assert len(good.sent) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_to_user_all_failed_returns_false():
    """全部连接失败 → False，连接全被摘除"""
    mgr = ConnectionManager()
    await mgr.connect(1, FakeWebSocket(fail=True))
    await mgr.connect(1, FakeWebSocket(fail=True))

    delivered = await mgr.send_to_user(1, {"type": "x", "data": {}})

    assert delivered is False
    assert mgr.connections_count(1) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_to_user_datetime_event_survives():
    """datetime 直塞事件经 dumps_event 兜底序列化，不打崩推送"""
    mgr = ConnectionManager()
    ws = FakeWebSocket()
    await mgr.connect(1, ws)

    event = envelope("notification.new", {"created_at": datetime.datetime.now()})
    delivered = await mgr.send_to_user(1, event)

    assert delivered is True
    assert "created_at" in ws.sent[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_users_isolated():
    """不同用户连接互不干扰"""
    mgr = ConnectionManager()
    ws_a, ws_b = FakeWebSocket(), FakeWebSocket()
    await mgr.connect(1, ws_a)
    await mgr.connect(2, ws_b)

    await mgr.send_to_user(1, envelope("notification.new", {"id": 1}))

    assert len(ws_a.sent) == 1
    assert ws_b.sent == []
