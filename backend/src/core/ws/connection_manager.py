"""per-user WebSocket 连接注册表（通知常驻订阅通道）。

连接按认证后的 user_id 归组（同一用户多标签页 = 多连接，推送全达）。
推送失败静默摘除断连——DB 是事实源，WS 只是加速器，30s 轮询兜底。

多进程演进注记：当前单进程架构（arq worker 内嵌主进程），send_notification
所在进程与持连进程相同，进程内单例直接可达；将来 ``--workers > 1`` 时需在
``send_to_user`` 后接 Redis pub/sub 跨进程广播。
"""
from __future__ import annotations

import asyncio

from fastapi import WebSocket
from novamind.core.middleware.structured_logging import get_logger
from novamind.core.ws.stream import dumps_event

logger = get_logger(__name__)


class ConnectionManager:
    """user_id → WebSocket 集合的进程内注册表。"""

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()  # 注册表增删互斥（同一事件循环内实际无竞争，防御性）

    def connections_count(self, user_id: int) -> int:
        """指定用户的活跃连接数（测试/监控用）。"""
        return len(self._connections.get(user_id, ()))

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        """注册连接（认证通过后调用）。"""
        async with self._lock:
            self._connections.setdefault(user_id, set()).add(websocket)

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        """摘除连接；用户最后一个连接移除后清掉空集合。"""
        async with self._lock:
            conns = self._connections.get(user_id)
            if conns is None:
                return
            conns.discard(websocket)
            if not conns:
                self._connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, event: dict) -> bool:
        """向用户的所有活跃连接推送事件。

        经 ``dumps_event`` 序列化（datetime 等兜底 ``default=str``）；
        逐连接 try/except：任何异常（断连/背压）→ 摘除该连接静默继续。
        无连接直接返回 False，零开销。

        Returns:
            是否至少有一个连接推送成功。
        """
        conns = self._connections.get(user_id)
        if not conns:
            return False

        payload = dumps_event(event)
        delivered = False
        # 遍历副本：discard 原集合时迭代安全
        for websocket in list(conns):
            try:
                await websocket.send_text(payload)
                delivered = True
            except Exception as e:
                logger.debug("通知 WS 推送失败，摘除连接", user_id=user_id, error=str(e))
                await self.disconnect(user_id, websocket)
        return delivered


# 进程内单例：send_notification（HTTP 请求或 arq 任务内）与 WS 端点同进程可达
manager = ConnectionManager()

__all__ = ["ConnectionManager", "manager"]
