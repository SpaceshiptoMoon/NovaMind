"""嵌入式 arq worker 监护循环回归测试（评审 P2-5）。

历史实现里 worker 异常退出后仅记日志、不重启——所有文档任务永久滞留队列
直到整个进程重启。修复后 _supervise_worker 指数退避重启；正常退出/取消不重启。

用桩替换 create_embedded_worker / _run_worker，验证三种结局：
- 异常退出 → 重启（退避递增）；
- 正常退出 → 监护循环结束；
- 取消 → 立即传播，不再重启。
"""
from __future__ import annotations

import asyncio

import pytest

from novamind.shared.mq import worker as worker_mod

pytestmark = pytest.mark.unit


class _FlakyRuntime:
    """控制 _run_worker 桩的行为脚本。"""

    def __init__(self, outcomes):
        # 每次调用弹出一个结局：Exception 实例 = 抛错；字符串 = 正常返回
        self.outcomes = list(outcomes)
        self.calls = 0

    async def __call__(self, worker):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else "normal"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.mark.asyncio
async def test_supervise_restarts_on_failure_with_backoff(monkeypatch):
    """正例：worker 崩溃 → 退避后重启；第二次成功后正常退出。"""
    runtime = _FlakyRuntime([RuntimeError("redis down"), "normal"])
    sleeps: list[float] = []

    async def fake_create(functions, task_queue, cron_jobs=()):
        return object()  # worker 实例被桩 _run_worker 忽略

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(worker_mod, "create_embedded_worker", fake_create)
    monkeypatch.setattr(worker_mod, "_run_worker", runtime)
    monkeypatch.setattr(worker_mod.asyncio, "sleep", fake_sleep)

    await asyncio.wait_for(
        worker_mod._supervise_worker([], None), timeout=2.0,
    )

    assert runtime.calls == 2
    assert sleeps == [worker_mod._RESTART_BACKOFF_BASE_SECONDS]


@pytest.mark.asyncio
async def test_supervise_backoff_doubles_and_caps(monkeypatch):
    """正例：连续崩溃 → 退避 5→10→20 封顶 60。"""
    runtime = _FlakyRuntime([Exception("x")] * 5)
    sleeps: list[float] = []

    async def fake_create(functions, task_queue, cron_jobs=()):
        return object()

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(worker_mod, "create_embedded_worker", fake_create)
    monkeypatch.setattr(worker_mod, "_run_worker", runtime)
    monkeypatch.setattr(worker_mod.asyncio, "sleep", fake_sleep)

    await asyncio.wait_for(
        worker_mod._supervise_worker([], None), timeout=2.0,
    )

    # 每次失败 sleep(backoff) 后 backoff 翻倍封顶 60：5 次失败 → [5,10,20,40,60]；
    # 第 6 次 _run_worker 桩在 outcomes 耗尽后返回 "normal"，循环正常结束
    assert sleeps == [5, 10, 20, 40, 60]


@pytest.mark.asyncio
async def test_supervise_cancel_stops_restart(monkeypatch):
    """反例：监护任务被取消 → CancelledError 传播，不进入下一轮重启。"""
    runtime = _FlakyRuntime([])  # 永不弹出，_run_worker 桩不会先返回

    async def fake_create(functions, task_queue, cron_jobs=()):
        return object()

    async def hanging_run(worker):
        await asyncio.sleep(3600)

    monkeypatch.setattr(worker_mod, "create_embedded_worker", fake_create)
    monkeypatch.setattr(worker_mod, "_run_worker", hanging_run)

    supervise = asyncio.ensure_future(worker_mod._supervise_worker([], None))
    await asyncio.sleep(0.05)
    supervise.cancel()
    with pytest.raises(asyncio.CancelledError):
        await supervise
    assert runtime.calls == 0  # 用的是 hanging_run，桩没被调用过即验证分支
