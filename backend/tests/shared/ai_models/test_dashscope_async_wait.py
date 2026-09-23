"""DashScope ASR 轮询事件循环隔离门禁（2026-09 链路审计 P0 回归）。

SDK ``Transcription.wait`` 是 ``while True + time.sleep`` 的同步轮询且无总超时：
- async 代码直接调用会冻结整个事件循环（worker 全部 job / API 全部请求停摆）；
- 任务卡 RUNNING 时无任何超时兜底。

本文件钉死两件事：
1. async 消费方（audio_utils / connection_testers）必须用 ``await_transcription_async``，
   不得 import/调用同步版 ``await_transcription``（AST 门禁，防回退）；
2. async 包装语义：轮询经 to_thread 下放（可并发）+ 总超时转译为 DashScopeTranscriptionError。
"""
import ast
import asyncio
from pathlib import Path

import pytest

from novamind.shared.ai_models.asr.dashscope_client import (
    DashScopeTranscriptionError,
    await_transcription,
    await_transcription_async,
)

SRC_ROOT = Path(__file__).resolve().parents[3] / "src"

# 允许直接引用同步版 await_transcription 的模块（定义处 + 纯文档场景）。
SYNC_WAIT_DEFINITION_MODULES = {
    "shared/ai_models/asr/dashscope_client.py",  # 同步实现本体
}


def _module_rel_path(node: ast.AST, src_root: Path) -> str:
    return str(Path(node.lineno and node.__dict__.get("file", "")).relative_to(src_root))


# ========== 1. AST 门禁：async 消费方不得触碰同步轮询 ==========


def _collect_sync_wait_references(file_path: Path) -> list[str]:
    """收集文件中引用 await_transcription（同步版）的位置描述。"""
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    refs: list[str] = []
    for node in ast.walk(tree):
        # from novamind.shared.ai_models.asr import await_transcription
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "await_transcription":
                    refs.append(f"import at line {node.lineno}")
        # from ...asr.dashscope_client import await_transcription
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith(
            "dashscope_client"
        ):
            for alias in node.names:
                if alias.name == "await_transcription":
                    refs.append(f"dashscope_client import at line {node.lineno}")
        # await_transcription(...) 直接调用
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "await_transcription":
                refs.append(f"call at line {node.lineno}")
    return refs


@pytest.mark.parametrize(
    "rel_path",
    [
        "engines/document/media/audio/audio_utils.py",
        "shared/ai_models/connection_testers/asr.py",
    ],
)
def test_async_consumers_must_use_async_wait_wrapper(rel_path):
    """P0 回归门禁：两个 async 消费方不得 import/调用同步版 await_transcription。"""
    refs = _collect_sync_wait_references(SRC_ROOT / rel_path)
    assert refs == [], (
        f"{rel_path} 引用了同步版 await_transcription（会冻结事件循环）：{refs}。"
        f"请改用 await_transcription_async。"
    )


def test_async_wrapper_exists_and_is_coroutine():
    """async 包装存在且是真协程函数。"""
    assert asyncio.iscoroutinefunction(await_transcription_async)
    assert not asyncio.iscoroutinefunction(await_transcription)


# ========== 2. async 包装语义：to_thread 隔离 + 总超时 ==========


def test_async_wrapper_runs_polling_off_event_loop(monkeypatch):
    """轮询在 worker 线程执行（to_thread），期间事件循环可响应其它任务。"""
    import threading

    poll_thread_ids: list[int] = []

    def fake_sync_wait(task_id: str) -> dict:
        poll_thread_ids.append(threading.get_ident())
        return {"task_status": "SUCCEEDED", "results": []}

    monkeypatch.setattr(
        "novamind.shared.ai_models.asr.dashscope_client.await_transcription",
        fake_sync_wait,
    )

    loop_still_responsive = False

    async def probe() -> None:
        nonlocal loop_still_responsive
        await asyncio.sleep(0.01)
        loop_still_responsive = True

    async def main() -> None:
        await asyncio.gather(
            await_transcription_async("task-1"),
            probe(),
        )

    asyncio.run(main())
    assert loop_still_responsive, "轮询期间事件循环被阻塞（未真正下放线程）"
    main_thread = threading.main_thread().ident
    assert poll_thread_ids and all(t != main_thread for t in poll_thread_ids), (
        "轮询跑在事件循环线程上"
    )


def test_async_wrapper_translates_timeout_to_business_error(monkeypatch):
    """任务卡 RUNNING 时总超时生效，TimeoutError 转译为 DashScopeTranscriptionError。

    注意在协程内部度量耗时：asyncio.run 退出时会 shutdown_default_executor()
    等待 to_thread 里仍在 sleep 的孤儿线程跑完，外层时钟会把这段算进去。
    """
    import time

    def hanging_wait(task_id: str) -> dict:
        time.sleep(30)  # 远超测试超时
        return {}

    monkeypatch.setattr(
        "novamind.shared.ai_models.asr.dashscope_client.await_transcription",
        hanging_wait,
    )

    elapsed: list[float] = []

    async def main() -> None:
        start = time.monotonic()
        with pytest.raises(DashScopeTranscriptionError, match="轮询超时"):
            await await_transcription_async("task-stuck", timeout_seconds=1)
        elapsed.append(time.monotonic() - start)

    asyncio.run(main())
    assert elapsed and elapsed[0] < 5, f"超时未在协程内生效（耗时 {elapsed}）"
