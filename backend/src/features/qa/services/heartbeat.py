"""
qa 流式心跳包装工具（批次 6.6 从 shared/utils 归位 qa 域——唯一消费者是 qa）。

为流式输出提供心跳机制，防止代理服务器或负载均衡器因超时断开连接；
同时提供「流死检测」：连续多个心跳间隔无新数据时判定流已终止，通过
``StreamHeartbeatOutcome`` 告知调用方内容被截断——调用方不得把半截内容
当作完整回答落库（评审 P1-1）。

关键实现约束（Python 3.12 asyncio.wait_for 语义陷阱）：
``wait_for(gen.__anext__(), timeout)`` 超时会 cancel ``__anext__`` 任务，
CancelledError 直接打入 generator 帧——对 AsyncOpenAI/httpx 流等价于关闭
连接，下一轮 ``__anext__()`` 抛 StopAsyncIteration，与「LLM 正常说完」
不可区分。因此 ``__anext__`` 必须放在独立 task 里并 ``shield``：
超时只放弃本次等待，generator 帧不被打扰，流保持存活可继续等待。
"""

import asyncio
import time
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field

from novamind.shared.ai_models.base_model import StreamChunk
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 心跳间隔内无新数据记一次静默；连续静默达到该值判定流死。
# 1 次静默 = LLM 端到端首 token / 慢推理的常见形态（15s+ 无输出但仍在工作），
# 不能据此断流；2 次静默（默认 30s 无任何字节）对正常生产者已不可能，
# 继续等只会把断流拖成用户可见的无限挂起。
DEAD_STREAM_SILENCE_COUNT = 2


@dataclass
class StreamHeartbeatOutcome:
    """心跳包装器的流结局标记（调用方据此决定落库语义）。

    Attributes:
        terminated_on_silence: 流因连续静默被判定死亡而终止（内容为截断）。
        silence_count: 终止时累计的连续静默次数。
        received_any: 流是否产出过任何数据块。
        heartbeat_count: 发出的心跳总次数（观测用）。
    """

    terminated_on_silence: bool = False
    silence_count: int = 0
    received_any: bool = False
    heartbeat_count: int = 0


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
        str: 原始数据或心跳注释（``: heartbeat\\n\\n``）
    """
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
            yield chunk
        except TimeoutError:
            logger.debug("SSE 心跳发送", elapsed_seconds=interval)
            yield ": heartbeat\n\n"
        except StopAsyncIteration:
            break


async def stream_with_heartbeat_structured(
    source: AsyncIterator[StreamChunk],
    interval: float = 15.0,
    outcome: StreamHeartbeatOutcome | None = None,
) -> AsyncGenerator[StreamChunk | str, None]:
    """Structured 版心跳包装器——用于 StreamChunk 类型的流，带流死检测。

    ``__anext__`` 在独立 task 中执行并 shield：单个 ``interval`` 超时只发心跳
    不杀流（慢推理/首 token 延迟安全）；连续 ``DEAD_STREAM_SILENCE_COUNT``
    次静默判定流死，置 ``outcome.terminated_on_silence`` 后终止并回收任务。
    流正常穷尽（``StopAsyncIteration`` 从任务内冒出）则干净结束、truncated
    不置位——shield 保证了该信号只可能来自上游真实终结，而非本包装器的超时
    cancel 误杀。

    Yields:
        StreamChunk: 数据块（reasoning 或 content）
        str: 心跳注释行（``: heartbeat\\n\\n``），调用者通过 isinstance 判断
    """
    result = outcome if outcome is not None else StreamHeartbeatOutcome()
    stream_iter = source.__aiter__()

    pending: asyncio.Task | None = None
    silence_count = 0

    while True:
        if pending is None:
            pending = asyncio.ensure_future(stream_iter.__anext__())
        try:
            chunk = await asyncio.wait_for(asyncio.shield(pending), timeout=interval)
            pending = None
            silence_count = 0
            result.received_any = True
            yield chunk
        except TimeoutError:
            silence_count += 1
            if silence_count >= DEAD_STREAM_SILENCE_COUNT:
                # 连续多个间隔无任何数据：判定流死，内容截断。任务取消交给
                # finally（此处流已不可恢复，等它没有意义）。
                result.terminated_on_silence = True
                result.silence_count = silence_count
                logger.warning(
                    "流式输出连续静默超限，判定流终止（内容可能截断）",
                    silence_intervals=silence_count,
                    interval_seconds=interval,
                )
                break
            result.heartbeat_count += 1
            logger.debug(
                "SSE 心跳发送（structured）",
                silence_count=silence_count,
                interval_seconds=interval,
            )
            yield ": heartbeat\n\n"
        except StopAsyncIteration:
            # shield 保证该信号只来自上游真实终结（超时路径不会 cancel 任务）
            pending = None
            break
        except asyncio.CancelledError:
            # 消费者（chat_stream）被取消：向上传播，任务在 finally 回收
            raise

    if pending is not None:
        pending.cancel()
        try:
            await pending
        except (asyncio.CancelledError, StopAsyncIteration, Exception):
            pass
        pending = None
    result.silence_count = silence_count
