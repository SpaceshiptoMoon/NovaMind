"""WebSocket 流式推送工具。

把 ``async generator`` yield 的事件 dict 推到 WebSocket；客户端断连时
``aclose`` generator 触发 service 内 ``asyncio.CancelledError`` 做清理。
4 个聊天流式端点（agent/qa/clawmate/deep_research）共用此工具。
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, Dict

from fastapi import WebSocket, WebSocketDisconnect


def envelope(event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """统一事件 envelope：``{"type": ..., "data": ...}``。

    取代 SSE 时代 4 端点三种不一致格式（``event:``+``data:`` / ``{type,data}`` /
    ``{event_type,data,timestamp}``），WS 化后统一为一种。
    """
    return {"type": event_type, "data": data}


async def run_stream_to_ws(
    websocket: WebSocket, event_gen: AsyncGenerator[Dict[str, Any], None]
) -> None:
    """把 yield dict 的 async generator 推到 WS。

    - 正常：``async for event: await websocket.send_json(event)``
    - 客户端断连：``WebSocketDisconnect`` 捕获后静默退出
    - 无论如何 ``finally: await event_gen.aclose()`` —— 触发 service generator
      内 ``asyncio.CancelledError``，让 service 做事务回滚/状态标记 CANCELLED 等清理
    """
    try:
        async for event in event_gen:
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        await event_gen.aclose()


__all__ = ["envelope", "run_stream_to_ws"]