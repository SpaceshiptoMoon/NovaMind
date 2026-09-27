"""heartbeat 流死检测回归测试（评审 P1-1）。

stream_with_heartbeat_structured 的历史实现里，wait_for 超时只是发心跳继续等，
对「上游停止产出但不终结」的半开流会无限超时循环；而对「流已终结」形态，
StopAsyncIteration 会让截断内容静默走完循环、被调用方当完整回答落库。

修复后：连续 DEAD_STREAM_SILENCE_COUNT 个间隔无数据 → 主动终止并置
terminated_on_silence；正常流（含超过单间隔的慢块）不受影响。正反两用例：
- 正例：慢流（块间隔 > interval）完整收完，truncated 不置位；
- 反例：流中途断供，第 2 次静默终止，truncated 置位且已收块不丢。
"""
from __future__ import annotations

import asyncio
import time

import pytest

from novamind.features.qa.services.heartbeat import (
    DEAD_STREAM_SILENCE_COUNT,
    StreamHeartbeatOutcome,
    stream_with_heartbeat_structured,
)
from novamind.shared.ai_models.base_model import StreamChunk

pytestmark = pytest.mark.unit


def _mk(chunk: str) -> StreamChunk:
    return StreamChunk(type="content", text=chunk)


async def _collect(gen):
    """收集包装器产出：(数据块文本列表, 心跳次数, outcome)。"""
    texts: list[str] = []
    heartbeats = 0
    async for item in gen:
        if isinstance(item, str):
            heartbeats += 1
        else:
            texts.append(item.text)
    return texts, heartbeats, gen


@pytest.mark.asyncio
async def test_slow_stream_completes_without_truncation(monkeypatch):
    """正例：慢流（块间隔超过单个 interval）不被误杀，完整收完。

    把 interval 压到 0.02s，块间隔 0.03s —— 单次静默即心跳（1 < 阈值 2），
    下一个块到达时静默计数清零，流正常终结且 truncated 不置位。
    """
    outcome = StreamHeartbeatOutcome()

    async def slow_stream():
        for piece in ["第一段", "第二段", "第三段"]:
            await asyncio.sleep(0.03)
            yield _mk(piece)

    texts, _heartbeats, _ = await _collect(
        stream_with_heartbeat_structured(slow_stream(), interval=0.02, outcome=outcome)
    )
    assert texts == ["第一段", "第二段", "第三段"]
    assert outcome.terminated_on_silence is False
    assert outcome.received_any is True


@pytest.mark.asyncio
async def test_dead_stream_terminates_and_marks_truncated():
    """反例：流产出两块后断供（半开——不终结生成器），连续静默达到阈值后
    主动终止，truncated 置位，已收到的块不丢失，总耗时不超过阈值 × interval。"""
    outcome = StreamHeartbeatOutcome()

    async def dead_stream():
        yield _mk("开头")
        yield _mk("部分")
        # 断供但不 return/raise —— 永久挂起形态（代理半开）
        await asyncio.sleep(3600)
        yield _mk("永不到达")

    interval = 0.05
    start = time.monotonic()
    texts = []
    async for item in stream_with_heartbeat_structured(dead_stream(), interval=interval, outcome=outcome):
        if not isinstance(item, str):
            texts.append(item.text)
    elapsed = time.monotonic() - start

    assert texts == ["开头", "部分"]
    assert outcome.terminated_on_silence is True
    assert outcome.silence_count == DEAD_STREAM_SILENCE_COUNT
    # 终止发生在 阈值×interval 附近而非挂满 3600s（留足调度余量）
    assert elapsed < DEAD_STREAM_SILENCE_COUNT * interval + 1.0


@pytest.mark.asyncio
async def test_silence_counter_resets_on_activity():
    """正例：静默 1 次（心跳）后恢复产出，计数清零，不触发终止。"""
    outcome = StreamHeartbeatOutcome()

    async def recovering_stream():
        yield _mk("早")
        await asyncio.sleep(0.06)  # > 0.04 interval：先心跳一次
        yield _mk("晚")

    texts, heartbeats, _ = await _collect(
        stream_with_heartbeat_structured(recovering_stream(), interval=0.04, outcome=outcome)
    )
    assert texts == ["早", "晚"]
    assert heartbeats >= 1
    assert outcome.terminated_on_silence is False


@pytest.mark.asyncio
async def test_consumer_cancel_closes_upstream_stream():
    """反例（子代理审查发现）：消费者中途取消时，挂起的 __anext__ 任务与
    上游流必须被就地关闭——否则底层 httpx 连接保持打开（每次断连泄漏
    一个 task + 一条连接）。历史实现回收代码在 CancelledError raise 之后
    的顺序位置，不可达。

    用上游生成器的 finally 是否执行来判定「流被关闭」。
    """
    outcome = StreamHeartbeatOutcome()
    upstream_closed = False

    async def slow_stream():
        nonlocal upstream_closed
        try:
            yield _mk("第一块")
            # 长静默：消费者会在心跳等待期间取消
            await asyncio.sleep(10)
            yield _mk("永不到达")
        finally:
            upstream_closed = True

    gen = stream_with_heartbeat_structured(slow_stream(), interval=0.05, outcome=outcome)
    received = []
    async for item in gen:
        if not isinstance(item, str):
            received.append(item.text)
            break  # 收到第一块后立即放弃生成器（模拟 WS 断连 → run_stream_to_ws aclose）

    await gen.aclose()

    assert received == ["第一块"]
    # aclose 在挂起点抛 GeneratorExit → 上游 finally 已执行（连接已关闭）
    assert upstream_closed is True
    assert outcome.terminated_on_silence is False
