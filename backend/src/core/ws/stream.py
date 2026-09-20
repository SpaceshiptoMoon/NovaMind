"""WebSocket 流式推送工具。

把 ``async generator`` yield 的事件 dict 推到 WebSocket；客户端断连时
``aclose`` generator 在挂起点抛 ``GeneratorExit``（async generator 的 aclose
抛 GeneratorExit 而非 CancelledError），触发 service 内
``except (asyncio.CancelledError, GeneratorExit)`` 做清理。
3 个聊天流式端点（agent/qa/deep_research）共用此工具。
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


def envelope(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """统一事件 envelope：``{"type": ..., "data": ...}``。

    取代 SSE 时代 4 端点三种不一致格式（``event:``+``data:`` / ``{type,data}`` /
    ``{event_type,data,timestamp}``），WS 化后统一为一种。
    """
    return {"type": event_type, "data": data}


def dumps_event(event: dict[str, Any]) -> str:
    """WS 事件 JSON 序列化。

    正常事件走快路径（与 ``WebSocket.send_json`` 等价）；service 组装的事件
    若含 datetime 等不可序列化对象（QA ``created_at`` 曾因此打崩 ASGI 连接），
    兜底 ``default=str`` 降级序列化，只影响该事件而不中断整个流。
    """
    try:
        return json.dumps(event, separators=(",", ":"), ensure_ascii=False)
    except TypeError:
        return json.dumps(
            event, separators=(",", ":"), ensure_ascii=False, default=str
        )


async def send_event(websocket: WebSocket, event: dict[str, Any]) -> None:
    """安全推送单个事件（``dumps_event`` + ``send_text``）。

    并发 send 场景（agent/deep_research 的 locked_send）也应经此函数，
    在各自锁内调用，保证兜底行为一致。
    """
    await websocket.send_text(dumps_event(event))


async def run_stream_to_ws(
    websocket: WebSocket,
    event_gen: AsyncGenerator[dict[str, Any], None],
    send_fn: Any | None = None,
) -> None:
    """把 yield dict 的 async generator 推到 WS。

    - 正常：``async for event: await send_fn(event)``（默认 ``send_event``，
      可传 ``send_fn`` 加锁，E5 异步审批并发 send 时用）
    - 客户端断连：``WebSocketDisconnect`` 捕获后静默退出
    - 无论如何 ``finally: await event_gen.aclose()`` —— 在挂起点抛
      ``GeneratorExit`` 进 service generator，触发其
      ``except (asyncio.CancelledError, GeneratorExit)`` 做事务回滚/状态标记
      CANCELLED 等清理（aclose 抛 GeneratorExit，不是 CancelledError）
    """
    send = send_fn or (lambda event: send_event(websocket, event))
    try:
        async for event in event_gen:
            await send(event)
    except WebSocketDisconnect:
        pass
    finally:
        await event_gen.aclose()


__all__ = ["envelope", "dumps_event", "send_event", "run_stream_to_ws"]