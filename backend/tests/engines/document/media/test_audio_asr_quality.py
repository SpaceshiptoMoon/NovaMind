"""本地 ASR 识别质量层回归：模型档位映射 / 幻觉过滤 / 转写参数透传 / 热词。

覆盖第一性原理判据（非案例拟合）：
- 幻觉段过滤：no_speech_prob 高且 avg_logprob 低 → 丢；正常段 → 留；
  相邻重复 → 折叠；非相邻重复 → 留（正常文档合法重复不误伤）。
- 声学能量交叉验证：短文本段 RMS dBFS 低于阈值 → 丢；响亮段/长文本段/
  无法验证（越界/解码失败）→ 留（失败方向安全）。
- 幻觉套话双门控：孤立超短段（结构门控）+ 套话短语（二次确认）→ 丢；
  上下文密集的真实口头禅 / 不含短语 / 超长文本 → 留。
- 转写参数链：AudioConfig 引擎参数 + hotwords + 质量键必须完整透传到子进程。
- 热词预检：编码失败降级为不注入，正常/无法探测透传。
- 空结果重试：默认关闭（None），配置语言后低置信空结果重试一次。
- 模型档位映射：faster-whisper-{slug} 家族 ↔ 档位 ↔ 缓存目录约定，
  显式目录最高优先，非法档位 fail fast。
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.engines.document.media.audio import audio_utils
from novamind.engines.document.media.audio.audio_utils import (
    DEFAULT_LOCAL_WHISPER_MODEL,
    _filter_hallucinated_segments,
    _filter_low_energy_segments,
    _filter_stock_phrase_segments,
    _segment_rms_dbfs,
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


def test_transcribe_invocation_matches_real_signature():
    """生产调用形态必须与 _transcribe_in_subprocess 真实签名兼容。

    历史 bug：调用侧把参数 dict 作第 5 个位置实参传入，而签名在 cpu_threads
    之后是 keyword-only——运行时必 TypeError（被上游包装成「本地 ASR 不可用」），
    现有 stub 因签名恰好接收该 dict 而未暴露。本测试用 inspect.signature.bind
    直接对生产构造形态做校验，防再次漂移。
    """
    import functools
    import inspect

    sig = inspect.signature(audio_utils._transcribe_in_subprocess)

    # 正：当前生产形态（partial + 关键字传参）必须 bind 成功
    invoke = functools.partial(
        audio_utils._transcribe_in_subprocess,
        "/tmp/a.mp3",
        None,
        "C:/models/fw-small",
        4,
        device="cpu",
        compute_type="int8",
        beam_size=3,
        vad_enabled=True,
        hotwords="热词",
    )
    sig.bind(*invoke.args, **invoke.keywords)

    # 反：历史坏形态（dict 作位置实参）必须 bind 失败——锁死对 bug 形态的拦截
    with pytest.raises(TypeError):
        sig.bind("/tmp/a.mp3", None, "C:/models/fw-small", 4, {"device": "cpu"})


def test_transcribe_params_passed_to_subprocess(monkeypatch):
    """AudioConfig 引擎参数 + hotwords 必须完整透传到子进程转写调用。"""
    captured = {}

    def _fake_transcribe(tmp_path, language, model_dir, cpu_threads, **kwargs):
        captured["language"] = language
        captured["kwargs"] = kwargs
        return {
            "segments": [_seg("内容")],
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

    def _fake_transcribe(tmp_path, language, model_dir, cpu_threads, **kwargs):
        captured["kwargs"] = kwargs
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


def test_build_engine_audio_config_passthrough_new_quality_keys(monkeypatch):
    """宿主构造 AudioConfig 必须透传两质量新键（YAML → 引擎全链对齐）。

    历史： ParsingConfig/config.py/loader.py/default.example 四处加了新键但
    _build_engine_audio_config 漏透传，引擎侧永远拿不到配置——本测试锁死透传。
    """
    from novamind.features.knowledge_space.services.media_processing import (
        _build_engine_audio_config,
    )
    from novamind.setting.yaml_config import get_config

    parsing = get_config().knowledge_base.parsing
    saved = (parsing.local_whisper_min_speech_dbfs, parsing.local_whisper_empty_result_retry_language)
    try:
        parsing.local_whisper_min_speech_dbfs = -35.0
        parsing.local_whisper_empty_result_retry_language = "zh"
        cfg = _build_engine_audio_config()
        assert cfg.local_whisper_min_speech_dbfs == -35.0
        assert cfg.local_whisper_empty_result_retry_language == "zh"
    finally:
        parsing.local_whisper_min_speech_dbfs, parsing.local_whisper_empty_result_retry_language = saved


# ==================== 声学能量交叉验证 ====================


def _tone_dbfs(amplitude: float, seconds: float, sr: int = 16000):
    """生成指定幅度的正弦波。RMS = 幅度/√2：0.5 → ≈ -9 dBFS，0.005 → ≈ -49 dBFS。"""
    import numpy as np

    t = np.arange(int(seconds * sr)) / sr
    return (amplitude * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)


def test_segment_rms_dbfs_loud_and_silent():
    """响亮正弦 ≈ -9 dBFS；全零窗口 → -inf；越界/空窗 → None。"""
    import numpy as np

    audio = _tone_dbfs(0.5, 2.0)
    dbfs = _segment_rms_dbfs(audio, 0.0, 1.0)
    assert dbfs is not None and -10.0 < dbfs < -8.0

    silence = np.zeros(16000, dtype=np.float32)
    assert _segment_rms_dbfs(silence, 0.0, 1.0) == float("-inf")

    # 反向：窗口越界 / 空窗 / None 音频 → None（无法验证，不丢段）
    assert _segment_rms_dbfs(audio, 10.0, 12.0) is None
    assert _segment_rms_dbfs(audio, 5.0, 5.0) is None
    assert _segment_rms_dbfs(None, 0.0, 1.0) is None


def test_energy_filter_drops_low_energy_short_keeps_loud_short():
    """短文本段：底噪上编造的低能量段丢；响亮真实段留。"""
    import numpy as np

    loud = _tone_dbfs(0.5, 10.0)          # ≈ -9 dBFS
    quiet = _tone_dbfs(0.005, 10.0)       # ≈ -49 dBFS（底噪级）
    audio = np.concatenate([loud, quiet])  # 前 10s 响亮，后 10s 底噪
    segments = [
        _seg("谢谢观看", start=0.0, end=2.0),   # 落在响亮区 → 留
        _seg("Bye.", start=10.0, end=12.0),     # 落在底噪区 → 丢
    ]
    kept, dropped = _filter_low_energy_segments(segments, audio, -40.0)
    assert dropped == 1
    assert [s["text"] for s in kept] == ["谢谢观看"]


def test_energy_filter_keeps_long_text_even_if_quiet():
    """长文本低能量段保留（能量判据只交叉验证短文本，防误伤轻声长内容）。"""
    quiet = _tone_dbfs(0.005, 10.0)
    long_text = "这是一段很长的轻声朗读内容不应当被能量判据误伤"
    assert len(long_text) > 15
    kept, dropped = _filter_low_energy_segments(
        [_seg(long_text, start=0.0, end=8.0)], quiet, -40.0
    )
    assert dropped == 0
    assert len(kept) == 1


def test_energy_filter_window_oob_or_no_audio_keeps():
    """窗口越界 / audio=None → 无法验证，全部保留（失败方向安全）。"""
    audio = _tone_dbfs(0.5, 1.0)
    segments = [_seg("短", start=50.0, end=52.0)]
    kept, dropped = _filter_low_energy_segments(segments, audio, -40.0)
    assert dropped == 0 and len(kept) == 1

    kept2, dropped2 = _filter_low_energy_segments(segments, None, -40.0)
    assert dropped2 == 0 and len(kept2) == 1


def test_energy_filter_disabled_when_min_dbfs_none():
    """min_dbfs=None → 过滤禁用（配置显式关闭路径）。"""
    kept, dropped = _filter_low_energy_segments([_seg("Bye.")], None, None)
    assert dropped == 0 and len(kept) == 1


def test_subprocess_wires_min_speech_dbfs_from_config(monkeypatch):
    """AudioConfig.local_whisper_min_speech_dbfs 必须经 partial 透传到子进程调用。"""
    captured = {}

    def _fake_transcribe(tmp_path, language, model_dir, cpu_threads, **kwargs):
        captured["kwargs"] = kwargs
        return {
            "segments": [_seg("内容")],
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
    cfg = AudioConfig(local_whisper_min_speech_dbfs=-35.0)
    asyncio.run(audio_utils.transcribe_audio_local(b"\x00" * 2048, "mp3", audio_config=cfg))
    assert captured["kwargs"]["min_speech_dbfs"] == -35.0


# ==================== 幻觉套话双门控 ====================


def test_phrase_filter_drops_isolated_stock_phrase():
    """正：片尾静音残留的孤立套话（短时长+短文本+大间隔）→ 丢。"""
    segments = [
        _seg("大家好今天我们讲知识库检索的内容", start=1.0, end=8.0),
        # 与前段间隔 3s、时长 2s、6 字 —— 结构+短语双命中
        _seg("谢谢观看", start=11.0, end=13.0),
    ]
    kept, dropped = _filter_stock_phrase_segments(segments)
    assert dropped == 1
    assert len(kept) == 1


def test_phrase_filter_keeps_phrase_with_dense_context():
    """反：上下文密集（无 2s 间隔）的套话是真实口头禅 → 留。

    剪辑视频里主播真的说「谢谢观看」时前后段紧邻，结构门控不满足，不丢。
    """
    segments = [
        _seg("今天的内容就到这里", start=0.0, end=3.0),
        _seg("谢谢观看", start=3.2, end=5.0),   # 与前段仅 0.2s 间隔
        _seg("我们下期再见", start=5.1, end=7.0),
    ]
    kept, dropped = _filter_stock_phrase_segments(segments)
    assert dropped == 0
    assert len(kept) == 3


def test_phrase_filter_keeps_long_or_dense_normal_segment():
    """反：命中短语但时长超限/文本超长的段不丢；不含短语的孤立短段不丢。"""
    long_text = "感谢观看本期深度解析系列节目" * 3   # 42 字 > 30 字上限
    segments = [
        _seg("片头正片开始", start=0.0, end=2.0),
        # 结构满足（孤立短段）但文本超长 → 结构门控拦截
        _seg(long_text, start=20.0, end=22.0),
        # 结构满足（孤立短段）但不含任何套话短语 → 短语确认不命中
        _seg("风声", start=40.0, end=41.0),
    ]
    kept, dropped = _filter_stock_phrase_segments(segments)
    assert dropped == 0
    assert [s["text"] for s in kept] == ["片头正片开始", long_text, "风声"]


# ==================== 热词预检 + 语言重试配置化 ====================


class _BoomTokenizer:
    """encode 即抛错的 tokenizer 桩（模拟热词含不可编码字符）。"""

    def encode(self, text):
        raise ValueError("unable to encode")


def test_precheck_hotwords_degrades_on_encode_error():
    """正：tokenizer 编码失败 → 返回 None（降级不注入），不抛错阻断转写。"""
    assert audio_utils._precheck_hotwords(
        SimpleNamespace(hf_tokenizer=_BoomTokenizer()), "热词 NovaMind"
    ) is None


def test_precheck_hotwords_passthrough_normal():
    """反：正常热词/空热词/无法探测 tokenizer 三条路径都原样透传。"""
    tok = SimpleNamespace(encode=lambda s: [1, 2])
    assert audio_utils._precheck_hotwords(SimpleNamespace(hf_tokenizer=tok), "热词") == "热词"
    assert audio_utils._precheck_hotwords(SimpleNamespace(hf_tokenizer=tok), None) is None
    assert audio_utils._precheck_hotwords(SimpleNamespace(), "无tokenizer探测") == "无tokenizer探测"


def test_empty_result_retry_disabled_by_default(monkeypatch):
    """反：retry_language 未配置（默认 None）→ 低置信空结果不再触发 zh 重试。

    历史行为是硬编码 zh 重试；配置化后默认关闭（与上游 faster-whisper 一致），
    只有显式配置 local_whisper_empty_result_retry_language 才重试。
    """
    calls = []

    def _fake_transcribe(tmp_path, language, model_dir, cpu_threads, **kwargs):
        calls.append(language)
        return {
            "segments": [],
            "language": "en",
            "language_probability": 0.3,
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
    cfg = AudioConfig(local_whisper_empty_result_retry_language=None)
    segments = asyncio.run(
        audio_utils.transcribe_audio_local(b"\x00" * 2048, "mp3", audio_config=cfg)
    )
    assert segments == []
    assert calls == [None]  # 只有首跑，无重试


def test_empty_result_retry_configured_language(monkeypatch):
    """正：配置 zh → 低置信空结果按 zh 重试一次，重试结果透出。"""
    calls = []

    def _fake_transcribe(tmp_path, language, model_dir, cpu_threads, **kwargs):
        calls.append(language)
        if language is None:
            return {
                "segments": [],
                "language": "en",
                "language_probability": 0.3,
                "duration": 1.0,
                "filtered_count": 0,
            }
        return {
            "segments": [_seg("重试后的中文内容")],
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
    cfg = AudioConfig(local_whisper_empty_result_retry_language="zh")
    segments = asyncio.run(
        audio_utils.transcribe_audio_local(b"\x00" * 2048, "mp3", audio_config=cfg)
    )
    assert calls == [None, "zh"]
    assert segments[0]["text"] == "重试后的中文内容"


def test_fingerprint_params_include_new_quality_keys():
    """asr_engine 指纹块必须含两质量新键——任一变化 → 快照失效 → RETRY 重转写。"""
    from novamind.features.knowledge_space.services.media_processing import (
        _audio_asr_fingerprint_params,
    )

    params = _audio_asr_fingerprint_params(
        "local", "faster-whisper-small",
        AudioConfig(local_whisper_min_speech_dbfs=-35.0,
                    local_whisper_empty_result_retry_language="zh"),
        None,
    )
    assert params["min_speech_dbfs"] == -35.0
    assert params["empty_result_retry_language"] == "zh"


# ==================== 路由层（家族匹配 + 默认链 + 热词） ====================


def _document():
    from types import SimpleNamespace

    return SimpleNamespace(id=1, uploader_id=42, file_type="mp3", filename="a.mp3")


def test_route_local_family_no_credentials():
    """faster-whisper 家族档位 → local 协议，不查凭证。"""
    from types import SimpleNamespace as SN
    from unittest.mock import AsyncMock

    from novamind.features.knowledge_space.services.media_processing import _resolve_asr_route

    mcs = SN(get_credentials_by_model=AsyncMock())
    protocol, model, key, url = asyncio.run(
        _resolve_asr_route(_document(), mcs, "faster-whisper-small")
    )
    assert (protocol, model, key, url) == ("local", "faster-whisper-small", None, None)
    assert mcs.get_credentials_by_model.await_count == 0


def test_route_invalid_local_slug_permanent_error():
    """非法本地档位 → PermanentProcessingError（配置错误 fail fast）。"""
    from types import SimpleNamespace as SN
    from unittest.mock import AsyncMock

    from novamind.features.knowledge_space.exceptions import PermanentProcessingError
    from novamind.features.knowledge_space.services.media_processing import _resolve_asr_route

    mcs = SN(get_credentials_by_model=AsyncMock())
    with pytest.raises(PermanentProcessingError, match="不支持的本地 ASR 模型档位"):
        asyncio.run(_resolve_asr_route(_document(), mcs, "faster-whisper-huge"))


def test_route_cloud_still_needs_credentials():
    """云端模型路由不受家族匹配影响：凭证缺失仍抛错。"""
    from types import SimpleNamespace as SN
    from unittest.mock import AsyncMock

    from novamind.features.knowledge_space.exceptions import PermanentProcessingError
    from novamind.features.knowledge_space.services.media_processing import _resolve_asr_route

    mcs = SN(get_credentials_by_model=AsyncMock(return_value=None))
    with pytest.raises(PermanentProcessingError, match="未找到 ASR 模型"):
        asyncio.run(_resolve_asr_route(_document(), mcs, "whisper-1"))
