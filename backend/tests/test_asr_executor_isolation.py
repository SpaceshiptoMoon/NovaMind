"""Regression test for ASR dedicated-executor isolation.

History: ``transcribe_audio_local`` ran ``model.transcribe`` via
``asyncio.to_thread`` on the shared default ``ThreadPoolExecutor``. Two audio
tasks starting within milliseconds of each other both called ``transcribe`` on the
SAME singleton ``WhisperModel`` instance concurrently. faster-whisper's CTranslate2
backend is not safe for concurrent ``transcribe`` on one instance — the process
crashed silently with no Python traceback. The shared pool was also hogged by
long transcribes, starving login's ``verify_password_async`` (which itself uses
``asyncio.to_thread`` for bcrypt) until login timed out.

Fix: ``transcribe_audio_local`` now runs ``model.transcribe`` on a dedicated
single-thread executor ``_asr_executor`` (``max_workers=1``). Transcribes serialize
(no concurrent same-instance call → no native crash) and the shared default pool is
freed for other ``to_thread`` consumers (login / MinIO / hash).
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.knowledge.media_processing.audio import audio_utils

pytestmark = pytest.mark.unit


class _FakeInfo:
    language = "zh"
    language_probability = 0.99
    duration = 1.0


class _FakeWhisperModel:
    """记录每次 transcribe 的起止时间，模拟 CPU 推理占用。

    非线程安全地写入 ``events`` 是故意的——如果两个转写真的并发跑，
    事件交错会让后面的区间断言失败，从而暴露回归。
    """

    def __init__(self):
        self.events: list[tuple[int, str, float]] = []
        self._counter = 0

    def transcribe(self, path, beam_size=5, word_timestamps=False, language=None):
        idx = self._counter
        self._counter += 1
        self.events.append((idx, "start", time.monotonic()))
        time.sleep(0.2)  # 模拟 CPU 推理占用一个线程
        self.events.append((idx, "end", time.monotonic()))
        return [], _FakeInfo()


async def _fake_get_model(model):
    return model


def _patch_asr(monkeypatch, fake_model):
    """绕过格式校验与真实模型加载，直接注入 fake 模型。"""
    monkeypatch.setattr(
        audio_utils,
        "_get_local_whisper_model",
        lambda: _fake_get_model(fake_model),
    )
    monkeypatch.setattr(
        audio_utils,
        "_validate_audio_for_local_asr",
        lambda b: ("mp3", "audio/mpeg"),
    )


def test_asr_executor_is_single_thread():
    """专用 executor 必须是单线程，从结构上保证转写串行、不并发同实例。"""
    assert audio_utils._asr_executor._max_workers == 1
    assert audio_utils._asr_executor._thread_name_prefix == "asr-transcribe"


@pytest.mark.asyncio
async def test_concurrent_transcribe_serialized_no_overlap(monkeypatch):
    """两个并发转写必须串行执行（区间不重叠），否则即并发调用同一模型实例。

    这条测试同时隐含证明转写走的是单线程 executor：若走默认共享池（多线程），
    两个 transcribe 会并行执行、区间重叠，断言失败。
    """
    fake_model = _FakeWhisperModel()
    _patch_asr(monkeypatch, fake_model)

    await asyncio.gather(
        audio_utils.transcribe_audio_local(b"\x00" * 32, "mp3"),
        audio_utils.transcribe_audio_local(b"\x00" * 32, "mp3"),
    )

    # 2 次调用 × start+end = 4 个事件
    assert len(fake_model.events) == 4

    calls: dict[int, dict[str, float]] = {}
    for idx, kind, t in fake_model.events:
        calls.setdefault(idx, {})[kind] = t
    intervals = sorted((c["start"], c["end"]) for c in calls.values())
    # 第二次转写的 start 必须不早于第一次的 end —— 串行无重叠
    assert intervals[1][0] >= intervals[0][1], (
        f"transcribe calls overlapped: {intervals} —— "
        "并发调用同一 WhisperModel 实例会触发 CTranslate2 原生层崩溃"
    )