"""伴生 runner 连接注册表：在线设备表 + call_id 多路复用。

RunnerRegistry 是云端派活的中枢：工具执行器按 device_id 取连接发 call，
经 Future 等对应 call_id 的 result；断线时清扫在途调用（立即失败）。
"""
import asyncio
from dataclasses import dataclass, field

from fastapi import WebSocket

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class RunnerConnection:
    """一条 runner 长连接的运行时状态。"""

    device_id: int
    user_id: int
    websocket: WebSocket
    pending: dict[str, asyncio.Future] = field(default_factory=dict)
    # 会话级 bash 授信表（session_id → True）；断线即失效，不持久
    trusted_sessions: set[str] = field(default_factory=set)

    def resolve_pending(self, call_id: str, payload: dict) -> bool:
        """回包唤醒等待方；call_id 不存在返回 False（迟到包静默丢弃）。"""
        fut = self.pending.pop(call_id, None)
        if fut is None or fut.done():
            return False
        fut.set_result(payload)
        return True

    def fail_all(self, error_code: str, message: str) -> int:
        """断线清扫：在途调用全部立即失败，返回清扫数量。"""
        n = 0
        for call_id, fut in self.pending.items():
            if not fut.done():
                fut.set_result({"ok": False, "error": message, "error_code": error_code})
                n += 1
        self.pending.clear()
        return n


class RunnerRegistry:
    """在线 runner 连接注册表（进程内单例，经 app.state 挂载）。"""

    def __init__(self):
        self._by_device: dict[int, RunnerConnection] = {}

    def register(self, conn: RunnerConnection) -> RunnerConnection | None:
        """注册连接；同设备旧连接存在则返回旧连接由调用方踢下线（新连接优先）。"""
        old = self._by_device.get(conn.device_id)
        self._by_device[conn.device_id] = conn
        return old

    def unregister(self, device_id: int, conn: RunnerConnection, error_code: str, message: str) -> int:
        """注销连接并清扫在途调用；连接已被替换时不清扫（归新连接管）。"""
        if self._by_device.get(device_id) is conn:
            del self._by_device[device_id]
        return conn.fail_all(error_code, message)

    def get_for_user(self, user_id: int, device_id: int) -> RunnerConnection | None:
        """取属主校验后的连接（工具执行器唯一入口）。"""
        conn = self._by_device.get(device_id)
        if conn is None or conn.user_id != user_id:
            return None
        return conn

    async def call(self, user_id: int, device_id: int, tool: str, args: dict, timeout: float) -> dict:
        """向指定设备派一次工具调用并等结果（多路复用，超时双边强制）。"""
        conn = self.get_for_user(user_id, device_id)
        if conn is None:
            return {"ok": False, "error": "设备不在线", "error_code": "DEVICE_OFFLINE"}
        call_id = f"c{len(conn.pending)}-{id(asyncio.current_task()) % 100000}-{asyncio.get_event_loop().time():.6f}"
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        conn.pending[call_id] = fut
        try:
            from novamind.core.ws.stream import dumps_event

            await conn.websocket.send_text(
                dumps_event({"type": "call", "data": {"call_id": call_id, "tool": tool, "args": args, "timeout": timeout}})
            )
        except Exception as e:
            conn.pending.pop(call_id, None)
            return {"ok": False, "error": f"派发失败: {e}", "error_code": "DEVICE_SEND_FAILED"}
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            conn.pending.pop(call_id, None)
            return {"ok": False, "error": f"工具执行超时（{timeout}s）", "error_code": "TOOL_TIMEOUT"}
