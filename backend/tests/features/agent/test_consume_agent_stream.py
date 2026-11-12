"""断连转后台续跑消费循环（consume_agent_stream，队列生产者-消费者架构）路径单测。

架构不变量：feeder 任务独占持有生成器逐事件入队，detach **永不取消 feeder**——
对外部任务的取消只打断消费循环的 queue.get，生成器在 feeder 里继续跑到终态
自然落库（初版直接 cancel 消费任务：取消落进生成器内部 await → 生成器被
CancelledError 关闭 → drain 瞬间耗尽轮次死亡，真机 e2e 揪出后改为本设计）。

验证核心不变量：
1. recv 侧断连信号 → detach：feeder 不受影响跑到耗尽、gen 不 aclose、
   running_turn 标记写入；
2. 显式 stop → cancel feeder → gen 收到 aclose（回滚链）、无 detach；
3. send 抛 OSError（兜底路径）→ 同样 detach；
4. 正常完成 → 全事件推送、无 detach、feeder 正常耗尽。

断连检测走 recv 侧（disconnect_event）：uvicorn 对客户端 RST 的 send 可能
挂在流控 drain 上不抛错（实测），send 抛 OSError 仅作兜底。
"""
import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.agent.api.routes import consume_agent_stream

pytestmark = pytest.mark.unit

# 30 个慢速流事件（0.05s/个）：保证断连/停止触发时轮次仍在途中
_EVENTS = (
    [{"type": "session", "data": {"session_id": "sess-9"}}]
    + [{"type": "content", "data": {"content": f"chunk-{i}"}} for i in range(28)]
    + [{"type": "done", "data": {}}]
)


class _TrackedGen:
    """可控事件生成器：记录消费进度与 aclose（GeneratorExit 注入）发生。"""

    def __init__(self, events):
        self.events = list(events)
        self.sent = 0
        self.aclosed = False
        self.exhausted = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.sent >= len(self.events):
            self.exhausted = True
            raise StopAsyncIteration
        ev = self.events[self.sent]
        self.sent += 1
        await asyncio.sleep(0.05)
        return ev

    async def aclose(self):
        self.aclosed = True


class _SendRecorder:
    """全事件正常推送并记录。"""

    def __init__(self):
        self.sent_events = []

    async def __call__(self, event):
        self.sent_events.append(event)


class _DisconnectingSend:
    """前 N 个事件正常推送，之后抛 OSError（send 侧断连兜底路径）。"""

    def __init__(self, fail_after):
        self.fail_after = fail_after
        self.sent_events = []

    async def __call__(self, event):
        if len(self.sent_events) >= self.fail_after:
            raise OSError("client disconnected")
        self.sent_events.append(event)


class _FakeService:
    def __init__(self):
        self.marked = []

    async def mark_turn_running(self, session_id):
        self.marked.append(session_id)


async def _wait_drain(holder, gen):
    """等 feeder（= holder['drain']）跑到生成器耗尽，并断言 gen 未被 aclose。"""
    drain = holder.get("drain")
    assert drain is not None, "detach 后 holder 必须持有 feeder task"
    await asyncio.wait_for(drain, timeout=10)
    assert gen.exhausted, "feeder 应消费到生成器耗尽"
    assert not gen.aclosed, "detach 路径不得 aclose（aclose 会回滚轮次）"


async def _wait_session_captured(current_session):
    """等 session 事件被捕获（断连早于 session 事件时标记无从写起）。"""
    for _ in range(100):
        if current_session["id"] is not None:
            return
        await asyncio.sleep(0.02)
    assert current_session["id"] is not None, "session 事件未被捕获"


@pytest.mark.asyncio
async def test_recv_disconnect_detaches_feeder_keeps_running():
    """recv 驱动断连（disconnect_event）→ detach：feeder 继续跑到耗尽。"""
    gen = _TrackedGen(_EVENTS)
    send = _SendRecorder()
    service = _FakeService()
    detach_state = {"detached": False}
    current_session = {"id": None}
    holder: dict = {"drain": None}
    stop_event = asyncio.Event()
    disconnect_event = asyncio.Event()

    task = asyncio.create_task(
        consume_agent_stream(
            gen,
            locked_send=send,
            service=service,
            stop_event=stop_event,
            disconnect_event=disconnect_event,
            detach_state=detach_state,
            current_session=current_session,
            holder=holder,
        )
    )
    await _wait_session_captured(current_session)
    assert len(send.sent_events) >= 1, "session 事件应已推送"
    disconnect_event.set()

    await asyncio.wait_for(task, timeout=5)  # 消费循环退出（feeder 仍在跑）
    assert detach_state["detached"] is True
    assert service.marked == ["sess-9"]

    # feeder 继续跑完（detach 不取消 feeder）；期间后续事件不再推送（已断连）
    await _wait_drain(holder, gen)
    final_pushed = len(send.sent_events)
    await asyncio.sleep(0.15)
    assert len(send.sent_events) == final_pushed, "detach 后不得再向死连接推送"


@pytest.mark.asyncio
async def test_explicit_stop_cancels_feeder_and_closes_generator():
    """显式 stop → cancel feeder → gen 收到 aclose（回滚链）、无 detach。"""
    gen = _TrackedGen(_EVENTS)
    send = _SendRecorder()
    service = _FakeService()
    detach_state = {"detached": False}
    current_session = {"id": None}
    holder: dict = {"drain": None}
    stop_event = asyncio.Event()
    disconnect_event = asyncio.Event()

    task = asyncio.create_task(
        consume_agent_stream(
            gen,
            locked_send=send,
            service=service,
            stop_event=stop_event,
            disconnect_event=disconnect_event,
            detach_state=detach_state,
            current_session=current_session,
            holder=holder,
        )
    )
    for _ in range(100):
        if len(send.sent_events) >= 2:
            break
        await asyncio.sleep(0.02)

    stop_event.set()
    await asyncio.wait_for(task, timeout=5)  # 正常返回（无异常上抛）

    assert gen.aclosed is True, "显式停止必须 aclose（走回滚链）"
    assert detach_state["detached"] is False
    assert holder.get("drain") is None


@pytest.mark.asyncio
async def test_send_oserror_break_falls_back_to_detach():
    """send 抛 OSError（兜底路径）→ 同样 detach + feeder 跑完。"""
    gen = _TrackedGen(_EVENTS)
    send = _DisconnectingSend(fail_after=1)  # 第 2 个事件时断连
    service = _FakeService()
    detach_state = {"detached": False}
    current_session = {"id": None}
    holder: dict = {"drain": None}
    stop_event = asyncio.Event()
    disconnect_event = asyncio.Event()

    await consume_agent_stream(
        gen,
        locked_send=send,
        service=service,
        stop_event=stop_event,
        disconnect_event=disconnect_event,
        detach_state=detach_state,
        current_session=current_session,
        holder=holder,
    )

    assert detach_state["detached"] is True
    assert service.marked == ["sess-9"]
    await _wait_drain(holder, gen)


@pytest.mark.asyncio
async def test_normal_completion_pushes_all_and_closes():
    """正常完成：全事件推送、无 detach、feeder 正常耗尽。"""
    events = [
        {"type": "session", "data": {"session_id": "sess-2"}},
        {"type": "done", "data": {}},
    ]
    gen = _TrackedGen(events)
    send = _SendRecorder()
    service = _FakeService()
    detach_state = {"detached": False}
    current_session = {"id": None}
    holder: dict = {"drain": None}
    stop_event = asyncio.Event()
    disconnect_event = asyncio.Event()

    await consume_agent_stream(
        gen,
        locked_send=send,
        service=service,
        stop_event=stop_event,
        disconnect_event=disconnect_event,
        detach_state=detach_state,
        current_session=current_session,
        holder=holder,
    )

    assert detach_state["detached"] is False
    assert holder.get("drain") is None
    assert gen.aclosed is True
    assert len(send.sent_events) == 2
    assert gen.exhausted is True


@pytest.mark.asyncio
async def test_cancel_while_parked_on_queue_routes_to_detach():
    """取消落在 queue.get 挂起点（recv 断连驱动）→ 吞取消转 detach（feeder 存活）。"""
    gen = _TrackedGen(_EVENTS)
    send = _SendRecorder()
    service = _FakeService()
    detach_state = {"detached": False}
    current_session = {"id": None}
    holder: dict = {"drain": None}
    stop_event = asyncio.Event()
    disconnect_event = asyncio.Event()

    task = asyncio.create_task(
        consume_agent_stream(
            gen,
            locked_send=send,
            service=service,
            stop_event=stop_event,
            disconnect_event=disconnect_event,
            detach_state=detach_state,
            current_session=current_session,
            holder=holder,
        )
    )
    await _wait_session_captured(current_session)
    disconnect_event.set()
    task.cancel()  # 取消落在 queue.get 等待（0.5s 窗口内的概率极低，用 cancel 直达）

    await asyncio.wait_for(task, timeout=5)  # 取消被吞、正常转 detach 返回
    assert detach_state["detached"] is True
    assert service.marked == ["sess-9"]
    await _wait_drain(holder, gen)
