"""
通用心跳工具

为 SSE 流式输出提供心跳机制，防止代理服务器或负载均衡器因超时断开连接。
"""

import asyncio
import time
from typing import AsyncIterator, AsyncGenerator, Union

from src.shared.ai_models.base_model import StreamChunk
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


async def stream_with_heartbeat(
    source: AsyncIterator[str],
    interval: float = 15.0,
) -> AsyncGenerator[str, None]:
    """
    为流式输出添加心跳机制的通用包装器

    当数据流在指定间隔内没有新数据时，发送 SSE 心跳注释，
    防止代理服务器或负载均衡器因超时断开连接。

    Args:
        source: 原始数据流异步迭代器
        interval: 心跳间隔（秒），默认 15 秒

    Yields:
        str: 原始数据或心跳注释（`: heartbeat\\n\\n`）
    """
    last_activity = time.monotonic()

    async def _with_timeout():
        """包装原始迭代器，用于与心跳竞争"""
        async for chunk in source:
            yield chunk

    stream_iter = _with_timeout().__aiter__()

    while True:
        try:
            chunk = await asyncio.wait_for(
                stream_iter.__anext__(),
                timeout=interval,
            )
            last_activity = time.monotonic()
            yield chunk
        except asyncio.TimeoutError:
            logger.debug(
                "SSE 心跳发送",
                elapsed=time.monotonic() - last_activity,
            )
            yield ": heartbeat\n\n"
        except StopAsyncIteration:
            break


async def stream_with_heartbeat_structured(
    source: AsyncIterator[StreamChunk],
    interval: float = 15.0,
) -> AsyncGenerator[Union[StreamChunk, str], None]:
    """Structured 版心跳包装器——用于 StreamChunk 类型的流

    Yields:
        StreamChunk: 数据块（reasoning 或 content）
        str: 心跳注释行（`: heartbeat\\n\\n`），调用者通过 isinstance 判断
    """
    last_activity = time.monotonic()

    async def _with_timeout():
        async for chunk in source:
            yield chunk

    stream_iter = _with_timeout().__aiter__()

    while True:
        try:
            chunk = await asyncio.wait_for(
                stream_iter.__anext__(),
                timeout=interval,
            )
            last_activity = time.monotonic()
            yield chunk
        except asyncio.TimeoutError:
            logger.debug(
                "SSE 心跳发送（structured）",
                elapsed=time.monotonic() - last_activity,
            )
            yield ": heartbeat\n\n"
        except StopAsyncIteration:
            break
