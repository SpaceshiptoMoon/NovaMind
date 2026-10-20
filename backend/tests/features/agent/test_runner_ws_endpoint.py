"""runner WS 端点回归测试：配对流/认证流/无效 token 拒绝 + call-result 全环。

RunnerDeviceService 整体以桩替换（避免 Redis + DB 装配链），协议帧与
连接注册表生命周期保持真实——这是云端派活的通道契约。call 全环不走
TestClient（portal 线程私有循环与注册表 Future 跨线程冲突），直接构造
RunnerConnection 假 websocket 做纯异步验证。
"""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
from unittest.mock import AsyncMock

from novamind.features.agent.api.runner_ws_routes import router as runner_ws_router
from novamind.features.agent.services.local_workspace.runner_registry import (
    RunnerConnection,
    RunnerRegistry,
)

pytestmark = pytest.mark.unit

_FAKE_DEVICE = SimpleNamespace(id=42, user_id=7, status="online")


class _StubService:
    """RunnerDeviceService 桩：pair/authenticate 两态可配。"""

    def __init__(self, pair_token=None, device_key="dk-real", pair_reject=False):
        self._pair_token = pair_token
        self._device_key = device_key
        self._pair_reject = pair_reject

    async def authenticate_hello(self, key):
        if self._pair_reject or key != self._device_key:
            return None
        return _FAKE_DEVICE

    async def pair(self, token, os_type, version):
        if self._pair_reject or token != self._pair_token:
            raise RuntimeError("invalid token")
        return _FAKE_DEVICE, self._device_key

    async def mark_seen(self, device_id, online):
        pass


def _make_app(monkeypatch, service: _StubService) -> FastAPI:
    async def _fake_build(db):
        return service

    monkeypatch.setattr(
        "novamind.features.agent.api.runner_ws_routes._build_device_service", _fake_build
    )
    app = FastAPI()
    app.include_router(runner_ws_router, prefix="/api/v1/agent/runner")
    app.state.runner_registry = RunnerRegistry()
    return app


def test_pairing_flow(monkeypatch):
    """首次配对：paired 帧（含一次性下发的 device_key）→ hello_ack → 注册在线。"""
    app = _make_app(monkeypatch, _StubService(pair_token="pt-abc", device_key="dk-real"))
    client = TestClient(app)
    with client.websocket_connect(
        "/api/v1/agent/runner/ws", subprotocols=["bearer.pt-abc"]
    ) as ws:
        ws.send_json({"type": "hello", "data": {"os": "windows", "version": "0.1.0"}})
        paired = ws.receive_json()
        assert paired["type"] == "paired"
        assert paired["data"]["device_key"] == "dk-real"
        assert paired["data"]["device_id"] == 42
        assert ws.receive_json()["type"] == "hello_ack"
        assert app.state.runner_registry.get_for_user(7, 42) is not None
        ws.send_json({"type": "bye", "data": {}})
    # 断开后注册表清空 + 在途调用清扫
    assert app.state.runner_registry.get_for_user(7, 42) is None


def test_device_key_reconnect_no_paired_frame(monkeypatch):
    """device_key 认证重连：不发 paired 帧，直接 hello_ack。"""
    app = _make_app(monkeypatch, _StubService(device_key="dk-real"))
    client = TestClient(app)
    with client.websocket_connect(
        "/api/v1/agent/runner/ws", subprotocols=["bearer.dk-real"]
    ) as ws:
        ws.send_json({"type": "hello", "data": {"os": "windows", "version": "0.1.0"}})
        assert ws.receive_json()["type"] == "hello_ack"
        ws.send_json({"type": "bye", "data": {}})


def test_bad_pairing_token_rejected(monkeypatch):
    """无效 token：服务器发错误帧后 close 4401——连接建立即被拒，收不到 hello_ack。"""
    app = _make_app(monkeypatch, _StubService(pair_reject=True))
    client = TestClient(app)
    with client.websocket_connect(
        "/api/v1/agent/runner/ws", subprotocols=["bearer.pt-bad"]
    ) as ws:
        ws.send_json({"type": "hello", "data": {"os": "windows", "version": "0.1.0"}})
        # 先是 error 帧，随后 close 4401（receive_json 到 close 时抛 WebSocketDisconnect）
        with pytest.raises(Exception):
            while True:
                ws.receive_json()


@pytest.mark.asyncio
async def test_registry_call_result_roundtrip():
    """云端派活全环：call 帧发出 → result 唤醒 Future → 超时/离线降级。"""
    registry = RunnerRegistry()
    ws = SimpleNamespace(send_text=AsyncMock())
    conn = RunnerConnection(device_id=42, user_id=7, websocket=ws)
    registry.register(conn)

    task = asyncio.create_task(registry.call(7, 42, "read", {"path": "a.py"}, timeout=5.0))
    await asyncio.sleep(0.01)
    frame = __import__("json").loads(ws.send_text.await_args.args[0])
    assert frame["type"] == "call"
    assert frame["data"]["tool"] == "read"

    conn.resolve_pending(frame["data"]["call_id"], {"ok": True, "result": "x=1"})
    result = await asyncio.wait_for(task, timeout=2.0)
    assert result["ok"] is True and result["result"] == "x=1"

    # 设备不在线：立即错误回包，不悬死
    out = await registry.call(7, 999, "read", {}, timeout=1.0)
    assert out["error_code"] == "DEVICE_OFFLINE"

    # 超时：Future 清理 + 超时错误
    out = await registry.call(7, 42, "glob", {}, timeout=0.05)
    assert out["error_code"] == "TOOL_TIMEOUT"
    assert not conn.pending
