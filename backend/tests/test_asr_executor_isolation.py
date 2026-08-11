"""Regression test for ASR subprocess isolation.

History: ``transcribe_audio_local`` ran ``model.transcribe`` via
``asyncio.to_thread`` on the shared default ``ThreadPoolExecutor``. Two audio
tasks starting within milliseconds of each other both called ``transcribe`` on the
SAME singleton ``WhisperModel`` instance concurrently. faster-whisper's CTranslate2
backend is not safe for concurrent ``transcribe`` on one instance — the process
crashed silently with no Python traceback. The shared pool was also hogged by
long transcribes, starving login's ``verify_password_async`` (which itself uses
``asyncio.to_thread`` for bcrypt) until login timed out.

Fix evolution:
- d01f219: dedicated single-thread ``ThreadPoolExecutor`` (``_asr_executor``) to
  serialize transcribes and free the shared pool.
- 0ff7fa0 / dec2fce: limit ``cpu_threads`` so the event loop thread gets a physical
  core. Still insufficient on hyperthreaded boxes — the executor thread and the
  event loop thread share one process and contend for CPU/GIL.
- this commit: replace ``ThreadPoolExecutor`` with ``ProcessPoolExecutor`` (spawn,
  ``max_workers=1``). int8 inference now runs in a child process — OS-level CPU/GIL
  isolation means the main process event loop is no longer starved by long
  transcribes, and a CTranslate2 segfault only kills the child, not the main process.
"""

import asyncio
import inspect
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.audio import audio_utils

pytestmark = pytest.mark.unit


def test_asr_executor_is_single_process():
    """专用 executor 必须是单进程 ProcessPoolExecutor，从结构上保证：
    - 转写串行（max_workers=1，无并发同实例 → 无 CTranslate2 崩溃）
    - OS 级 CPU/GIL 隔离（子进程推理，主进程事件循环不被饿死）
    """
    assert isinstance(audio_utils._asr_executor, ProcessPoolExecutor)
    assert audio_utils._asr_executor._max_workers == 1


def test_transcribe_in_subprocess_is_module_level():
    """子进程 worker 必须是模块级函数（spawn 经 pickle 引用，需可 import）。"""
    assert inspect.isfunction(audio_utils._transcribe_in_subprocess)
    assert audio_utils._transcribe_in_subprocess.__module__ == audio_utils.__name__


def _make_fake_transcribe():
    """返回 (fake 函数, events 列表)。fake 记录起止时间 + sleep 模拟 CPU 推理。

    非线程安全地写入 ``events`` 是故意的——如果两个转写真的并发跑，
    事件交错会让后面的区间断言失败，从而暴露回归。
    """
    events: list[tuple[int, str, float]] = []
    counter = [0]

    def _fake(tmp_path, language, model_dir, cpu_threads):
        idx = counter[0]
        counter[0] += 1
        events.append((idx, "start", time.monotonic()))
        time.sleep(0.2)  # 模拟 CPU 推理占用一个线程
        events.append((idx, "end", time.monotonic()))
        return {
            "segments": [],
            "language": "zh",
            "language_probability": 0.99,
            "duration": 1.0,
        }

    return _fake, events


def _patch_asr(monkeypatch, fake_transcribe):
    """绕过格式校验、模型目录解析与真实子进程，让 fake 在主进程线程跑。"""
    monkeypatch.setattr(
        audio_utils,
        "_validate_audio_for_local_asr",
        lambda b: ("mp3", "audio/mpeg"),
    )
    # 模型目录校验：返回一个真实存在的目录，通过 model_dir.exists()
    monkeypatch.setattr(
        audio_utils,
        "_resolve_local_whisper_model_dir",
        lambda audio_config=None: BACKEND_ROOT,
    )
    monkeypatch.setattr(audio_utils, "_transcribe_in_subprocess", fake_transcribe)
    # 用单线程 ThreadPoolExecutor 替代 ProcessPoolExecutor，让 fake 在主进程线程跑，
    # 验证 max_workers=1 的串行语义（不依赖真实子进程/模型）。
    monkeypatch.setattr(
        audio_utils,
        "_asr_executor",
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr-test"),
    )


@pytest.mark.asyncio
async def test_concurrent_transcribe_serialized_no_overlap(monkeypatch):
    """两个并发转写必须串行执行（区间不重叠），否则即并发调用同一模型实例。

    这条测试同时隐含证明转写走的是单 worker executor：若走多线程共享池，
    两个 transcribe 会并行执行、区间重叠，断言失败。
    """
    fake_transcribe, events = _make_fake_transcribe()
    _patch_asr(monkeypatch, fake_transcribe)

    await asyncio.gather(
        audio_utils.transcribe_audio_local(b"\x00" * 1024, "mp3"),
        audio_utils.transcribe_audio_local(b"\x00" * 1024, "mp3"),
    )

    # 2 次调用 × start+end = 4 个事件
    assert len(events) == 4

    calls: dict[int, dict[str, float]] = {}
    for idx, kind, t in events:
        calls.setdefault(idx, {})[kind] = t
    intervals = sorted((c["start"], c["end"]) for c in calls.values())
    # 第二次转写的 start 必须不早于第一次的 end —— 串行无重叠
    assert intervals[1][0] >= intervals[0][1], (
        f"transcribe calls overlapped: {intervals} —— "
        "并发调用同一 WhisperModel 实例会触发 CTranslate2 原生层崩溃"
    )