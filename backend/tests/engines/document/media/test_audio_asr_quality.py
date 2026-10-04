"""本地 ASR 识别质量层回归：模型档位映射 / 幻觉过滤 / 转写参数透传 / 热词。

覆盖第一性原理判据（非案例拟合）：
- 幻觉段过滤：no_speech_prob 高且 avg_logprob 低 → 丢；正常段 → 留；
  相邻重复 → 折叠；非相邻重复 → 留（正常文档合法重复不误伤）。
- 转写参数链：AudioConfig 引擎参数 + hotwords 必须完整透传到子进程调用。
- 模型档位映射：faster-whisper-{slug} 家族 ↔ 档位 ↔ 缓存目录约定，
  显式目录最高优先，非法档位 fail fast。
"""

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.engines.document.media.audio import audio_utils
from novamind.engines.document.media.audio.audio_utils import (
    DEFAULT_LOCAL_WHISPER_MODEL,
    _filter_hallucinated_segments,
    split_local_whisper_model_name,
)
from novamind.shared.config import AudioConfig

pytestmark = pytest.mark.unit


# ==================== 模型档位映射 ====================


def test_split_local_whisper_family_models():
    """本地家族各档位名 → 正确 slug；非家族名 → None（按云端处理）。"""
    assert split_local_whisper_model_name("faster-whisper-tiny") == "tiny"
    assert split_local_whisper_model_name("faster-whisper-large-v3") == "large-v3"
    assert split_local_whisper_model_name("paraformer-v2") is None
    assert split_local_whisper_model_name("whisper-1") is None
    assert split_local_whisper_model_name("") is None
    assert split_local_whisper_model_name(None) is None


def test_split_local_whisper_invalid_slug_raises():
    """家族名 + 非法档位 → ValueError（fail fast，不静默落到云端路由）。"""
    with pytest.raises(ValueError, match="不支持的本地 ASR 模型档位"):
        split_local_whisper_model_name("faster-whisper-huge")


def test_default_model_dir_respects_slug():
    """档位 → 缓存目录命名约定 backend/.cache/faster-whisper/{slug}。"""
    d = audio_utils.default_faster_whisper_cache_dir("small")
    assert d.name == "small"
    assert "faster-whisper" in str(d)


def test_resolve_model_dir_priority():
    """目录解析优先级：显式目录 > 档位名 > 默认档。"""
    # 显式目录最高优先
    explicit = audio_utils._resolve_local_whisper_model_dir(
        AudioConfig(local_whisper_model_dir="/models/w", local_whisper_model="tiny")
    )
    assert explicit == Path("/models/w")

    # 无显式目录 → 档位名 → 缓存约定
    by_slug = audio_utils._resolve_local_whisper_model_dir(
        AudioConfig(local_whisper_model="small")
    )
    assert by_slug.name == "small"

    # 全空 → 引擎默认档
    fallback = audio_utils._resolve_local_whisper_model_dir(AudioConfig())
    assert fallback.name == DEFAULT_LOCAL_WHISPER_MODEL


# ==================== 幻觉段过滤 ====================


def _seg(text, no_speech=0.1, logprob=-0.3, start=0.0, end=1.0):
    return {
        "text": text,
        "start": start,
        "end": end,
        "avg_logprob": logprob,
        "no_speech_prob": no_speech,
    }


def test_filter_drops_hallucinated_keeps_normal():
    """幻觉判据：双高（无语音概率高 + 对数概率低）才丢；单高不丢（反向用例）。"""
    segments = [
        _seg("正常语音段"),
        _seg("静音段编造文本", no_speech=0.9, logprob=-1.5),   # 双高 → 丢
        _seg("有把握的段", no_speech=0.9, logprob=-0.2),        # 仅 no_speech 高 → 留
        _seg("低置信但语音在", no_speech=0.2, logprob=-1.8),    # 仅 logprob 低 → 留
    ]
    kept, dropped = _filter_hallucinated_segments(segments)
    assert dropped == 1
    assert [s["text"] for s in kept] == ["正常语音段", "有把握的段", "低置信但语音在"]


def test_filter_collapses_adjacent_duplicates_only():
    """相邻重复折叠；非相邻重复（合法内容）保留。"""
    segments = [
        _seg("谢谢观看", start=0, end=2),
        _seg("谢谢观看", start=2, end=4),     # 相邻重复 → 折叠
        _seg("中间插播内容", start=4, end=6),
        _seg("谢谢观看", start=6, end=8),     # 非相邻重复 → 留
    ]
    kept, dropped = _filter_hallucinated_segments(segments)
    assert dropped == 1
    assert len(kept) == 3
    assert kept[-1]["text"] == "谢谢观看"


def test_filter_missing_fields_no_drop():
    """字段缺失（云端来源等）不误丢：概率缺省按「正常」处理。"""
    segments = [{"text": "无概率字段段", "start": 0.0, "end": 1.0}]
    kept, dropped = _filter_hallucinated_segments(segments)
    assert dropped == 0
    assert len(kept) == 1


# ==================== 转写参数透传 ====================


def test_transcribe_params_passed_to_subprocess(monkeypatch):
    """AudioConfig 引擎参数 + hotwords 必须完整透传到子进程转写调用。"""
    captured = {}

    def _fake_transcribe(tmp_path, language, model_dir, cpu_threads, transcribe_kwargs=None):
        captured["language"] = language
        captured["kwargs"] = transcribe_kwargs or {}
        return {
            "segments": [_seg("内容")],
            "language": "zh",
            "language_probability": 0.99,
            "duration": 1.0,
            "filtered_count": 0,
        }

    import concurrent.futures.thread as _t

    monkeypatch.setattr(audio_utils, "_validate_audio_for_local_asr", lambda b: ("mp3", "audio/mpeg"))
    monkeypatch.setattr(
        audio_utils, "_resolve_local_whisper_model_dir",
        lambda audio_config=None: BACKEND_ROOT,
    )
    monkeypatch.setattr(audio_utils, "_transcribe_in_subprocess", _fake_transcribe)
    monkeypatch.setattr(
        audio_utils, "_asr_executor",
        __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(max_workers=1),
    )

    cfg = AudioConfig(
        local_whisper_model="small",
        local_whisper_device="cpu",
        local_whisper_compute_type="int8",
        local_whisper_beam_size=3,
        local_whisper_vad_enabled=False,
    )
    segments = asyncio.run(
        audio_utils.transcribe_audio_local(
            b"\x00" * 2048, "mp3", language="zh",
            audio_config=cfg, hotwords=["NovaMind", "知识库"],
        )
    )
    assert segments[0]["text"] == "内容"
    kw = captured["kwargs"]
    assert kw["device"] == "cpu"
    assert kw["compute_type"] == "int8"
    assert kw["beam_size"] == 3
    assert kw["vad_enabled"] is False
    assert kw["hotwords"] == "NovaMind 知识库"  # 空格拼接


def test_transcribe_hotwords_empty_is_none(monkeypatch):
    """空热词列表 → None（不向 faster-whisper 传空串）。"""
    captured = {}

    def _fake_transcribe(tmp_path, language, model_dir, cpu_threads, transcribe_kwargs=None):
        captured["kwargs"] = transcribe_kwargs or {}
        return {
            "segments": [],
            "language": "zh",
            "language_probability": 0.99,
            "duration": 1.0,
            "filtered_count": 0,
        }

    monkeypatch.setattr(audio_utils, "_validate_audio_for_local_asr", lambda b: ("mp3", "audio/mpeg"))
    monkeypatch.setattr(
        audio_utils, "_resolve_local_whisper_model_dir",
        lambda audio_config=None: BACKEND_ROOT,
    )
    monkeypatch.setattr(audio_utils, "_transcribe_in_subprocess", _fake_transcribe)
    monkeypatch.setattr(
        audio_utils, "_asr_executor",
        __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(max_workers=1),
    )
    asyncio.run(audio_utils.transcribe_audio_local(b"\x00" * 2048, "mp3", hotwords=[]))
    assert captured["kwargs"]["hotwords"] is None


# ==================== 路由层（家族匹配 + 默认链 + 热词） ====================


def _document():
    from types import SimpleNamespace

    return SimpleNamespace(id=1, uploader_id=42, file_type="mp3", filename="a.mp3")


def test_route_local_family_no_credentials():
    """faster-whisper 家族档位 → local 协议，不查凭证。"""
    from novamind.features.knowledge_space.services.media_processing import _resolve_asr_route
    from unittest.mock import AsyncMock
    from types import SimpleNamespace as SN

    mcs = SN(get_credentials_by_model=AsyncMock())
    protocol, model, key, url = asyncio.run(
        _resolve_asr_route(_document(), mcs, "faster-whisper-small")
    )
    assert (protocol, model, key, url) == ("local", "faster-whisper-small", None, None)
    assert mcs.get_credentials_by_model.await_count == 0


def test_route_invalid_local_slug_permanent_error():
    """非法本地档位 → PermanentProcessingError（配置错误 fail fast）。"""
    from novamind.features.knowledge_space.exceptions import PermanentProcessingError
    from novamind.features.knowledge_space.services.media_processing import _resolve_asr_route
    from unittest.mock import AsyncMock
    from types import SimpleNamespace as SN

    mcs = SN(get_credentials_by_model=AsyncMock())
    with pytest.raises(PermanentProcessingError, match="不支持的本地 ASR 模型档位"):
        asyncio.run(_resolve_asr_route(_document(), mcs, "faster-whisper-huge"))


def test_route_cloud_still_needs_credentials():
    """云端模型路由不受家族匹配影响：凭证缺失仍抛错。"""
    from novamind.features.knowledge_space.exceptions import PermanentProcessingError
    from novamind.features.knowledge_space.services.media_processing import _resolve_asr_route
    from unittest.mock import AsyncMock
    from types import SimpleNamespace as SN

    mcs = SN(get_credentials_by_model=AsyncMock(return_value=None))
    with pytest.raises(PermanentProcessingError, match="未找到 ASR 模型"):
        asyncio.run(_resolve_asr_route(_document(), mcs, "whisper-1"))
