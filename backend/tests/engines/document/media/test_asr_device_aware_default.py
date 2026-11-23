"""本地 ASR 默认档位按设备自动选择 + 默认档未预装时的降级（回归）。

背景：默认档位此前固定为 large-v3——有 GPU 的机器用不上卡，没有 GPU 的机器要么在
YAML 手动降档，要么用 CPU 硬跑 large-v3。现在档位留空时按推理设备选默认档
（有 CUDA → large-v3，仅 CPU → small），显式档位不被改写；部署预装脚本与宿主
路由共用引擎的同一解析，三处不会漂移。

覆盖：
- 默认档位跟随设备；显式档位 / 显式设备优先；探测调用异常按无卡处理；
- 默认档未预装：另一个默认档已在本地 → 降级并告警；都没有 → 报错并点名应下载
  的档位；显式档位 / 目录缺失 → 照旧报错，不静默换成别的模型；
- 部署预装脚本、宿主路由出的档位与引擎实际加载的档位一致。
"""
import asyncio
import importlib.util
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

# backend/tests/engines/document/media/<this file> → four levels up is backend/
BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.engines.document.media.audio import audio_utils
from novamind.engines.document.media.audio.audio_utils import (
    DEFAULT_LOCAL_WHISPER_CPU_MODEL,
    DEFAULT_LOCAL_WHISPER_MODEL,
)
from novamind.shared.config import AudioConfig

pytestmark = pytest.mark.unit


def _gpu(monkeypatch, available: bool) -> None:
    """直接给定「引擎探测到 / 探测不到 CUDA」。"""
    monkeypatch.setattr(audio_utils, "_cuda_available", lambda: available)


@pytest.fixture(autouse=True)
def _no_cuda_probe_cache():
    """真实探测函数带进程内缓存：用例之间不残留。"""
    yield
    getattr(audio_utils._cuda_available, "cache_clear", lambda: None)()


# ==================== 档位解析 ====================


def test_default_tier_follows_the_device(monkeypatch):
    """档位留空：有 CUDA → large-v3；仅 CPU → small（缓存目录命名约定不变）。"""
    assert DEFAULT_LOCAL_WHISPER_CPU_MODEL == "small"
    _gpu(monkeypatch, True)
    assert audio_utils.resolve_local_whisper_device(AudioConfig()) == "cuda"
    assert audio_utils.resolve_local_whisper_model_slug(AudioConfig()) == DEFAULT_LOCAL_WHISPER_MODEL
    assert audio_utils._resolve_local_whisper_model_dir(AudioConfig()).name == DEFAULT_LOCAL_WHISPER_MODEL
    _gpu(monkeypatch, False)
    assert audio_utils.resolve_local_whisper_device(AudioConfig()) == "cpu"
    assert audio_utils.resolve_local_whisper_model_slug(AudioConfig()) == DEFAULT_LOCAL_WHISPER_CPU_MODEL
    assert audio_utils._resolve_local_whisper_model_dir(AudioConfig()).name == DEFAULT_LOCAL_WHISPER_CPU_MODEL


def test_explicit_tier_is_never_rewritten(monkeypatch):
    """显式档位在任何设备下都原样生效——无 GPU 也用 large-v3 是用户的明确选择。"""
    _gpu(monkeypatch, False)
    forced_large = AudioConfig(local_whisper_model="large-v3")
    assert audio_utils.resolve_local_whisper_model_slug(forced_large) == "large-v3"
    assert audio_utils._resolve_local_whisper_model_dir(forced_large).name == "large-v3"
    _gpu(monkeypatch, True)
    assert audio_utils.resolve_local_whisper_model_slug(AudioConfig(local_whisper_model="tiny")) == "tiny"


def test_explicit_device_wins_over_the_probe(monkeypatch):
    """显式 local_whisper_device 优先于探测：有卡的机器强制 cpu 也选 CPU 默认档。"""
    _gpu(monkeypatch, True)
    forced_cpu = AudioConfig(local_whisper_device="cpu")
    assert audio_utils.resolve_local_whisper_device(forced_cpu) == "cpu"
    assert audio_utils.resolve_local_whisper_model_slug(forced_cpu) == DEFAULT_LOCAL_WHISPER_CPU_MODEL
    assert audio_utils.resolve_local_whisper_device(AudioConfig(local_whisper_device="CUDA")) == "cuda"
    _gpu(monkeypatch, False)
    assert (
        audio_utils.resolve_local_whisper_model_slug(AudioConfig(local_whisper_device="cuda"))
        == DEFAULT_LOCAL_WHISPER_MODEL
    )


def test_cuda_probe_failure_counts_as_no_gpu(monkeypatch):
    """探测调用本身抛异常 → 按无卡处理（CPU 默认档），不让转写失败。"""
    import ctranslate2

    def _broken_probe():
        raise RuntimeError("driver broken")

    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", _broken_probe)
    audio_utils._cuda_available.cache_clear()
    assert audio_utils._cuda_available() is False
    assert audio_utils.resolve_local_whisper_device(AudioConfig()) == "cpu"


# ==================== 默认档未预装时的降级 ====================


@pytest.fixture
def cache_root(tmp_path, monkeypatch):
    """把档位缓存目录指到临时目录；返回「返回某档位目录」的函数（按需 mkdir 模拟已预装）。"""
    root = tmp_path / "faster-whisper"

    def _cache_dir(model_slug: str = DEFAULT_LOCAL_WHISPER_MODEL) -> Path:
        return root / model_slug

    monkeypatch.setattr(audio_utils, "default_faster_whisper_cache_dir", _cache_dir)
    return _cache_dir


def _transcribe_locally(monkeypatch, audio_config, captured: dict) -> list:
    """走 transcribe_audio_local 的真实前置流程（档位解析 → 存在性检查 → 降级），
    只把格式校验与子进程推理换成假实现，并记录实际交给子进程的模型目录名。"""

    def _fake_subprocess(tmp_file, language, model_dir, cpu_threads, **kwargs):
        captured["model_dir"] = Path(model_dir).name
        return {
            "segments": [],
            "language": "zh",
            "language_probability": 0.99,
            "duration": 1.0,
            "filtered_count": 0,
        }

    monkeypatch.setattr(audio_utils, "_validate_audio_for_local_asr", lambda b: ("mp3", "audio/mpeg"))
    monkeypatch.setattr(audio_utils, "_transcribe_in_subprocess", _fake_subprocess)
    executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(audio_utils, "_asr_executor", executor)
    try:
        return asyncio.run(
            audio_utils.transcribe_audio_local(b"\x00" * 2048, "mp3", audio_config=audio_config)
        )
    finally:
        executor.shutdown(wait=False)


def test_no_gpu_uses_small_once_downloaded(monkeypatch, cache_root):
    """无 GPU 的机器部署期预装 small：运行时直接用 small。"""
    _gpu(monkeypatch, False)
    cache_root(DEFAULT_LOCAL_WHISPER_CPU_MODEL).mkdir(parents=True)
    captured: dict = {}
    _transcribe_locally(monkeypatch, AudioConfig(), captured)
    assert captured["model_dir"] == "small"


def test_gpu_uses_large_v3_once_downloaded(monkeypatch, cache_root):
    """有 GPU 的机器部署期预装 large-v3：运行时直接用 large-v3。"""
    _gpu(monkeypatch, True)
    cache_root(DEFAULT_LOCAL_WHISPER_MODEL).mkdir(parents=True)
    captured: dict = {}
    _transcribe_locally(monkeypatch, AudioConfig(), captured)
    assert captured["model_dir"] == "large-v3"


def test_no_gpu_without_small_degrades_to_downloaded_large_v3(monkeypatch, cache_root, caplog):
    """存量无 GPU 部署只预装过 large-v3：small 还没下载时先用 large-v3 跑完这次转写并
    告警——升级不把「能跑但慢」变成「直接失败」。"""
    _gpu(monkeypatch, False)
    cache_root(DEFAULT_LOCAL_WHISPER_MODEL).mkdir(parents=True)
    captured: dict = {}
    with caplog.at_level(logging.WARNING, logger=audio_utils.logger.name):
        _transcribe_locally(monkeypatch, AudioConfig(), captured)
    assert captured["model_dir"] == "large-v3"
    assert DEFAULT_LOCAL_WHISPER_MODEL in caplog.text
    assert DEFAULT_LOCAL_WHISPER_CPU_MODEL in caplog.text
    assert f"--model {DEFAULT_LOCAL_WHISPER_CPU_MODEL}" in caplog.text


def test_gpu_without_large_v3_degrades_to_small(monkeypatch, cache_root):
    """反向：GPU 不可用、只下载了 small 时，GPU 默认档缺失同样降级到已有的 small。"""
    _gpu(monkeypatch, True)
    cache_root(DEFAULT_LOCAL_WHISPER_CPU_MODEL).mkdir(parents=True)
    captured: dict = {}
    _transcribe_locally(monkeypatch, AudioConfig(), captured)
    assert captured["model_dir"] == "small"


def test_nothing_downloaded_names_the_tier_to_download(monkeypatch, cache_root):
    """两个默认档都没有：照旧报错，指引里点名当前设备该下载的档位。"""
    _gpu(monkeypatch, False)
    captured: dict = {}
    with pytest.raises(RuntimeError, match=f"--model {DEFAULT_LOCAL_WHISPER_CPU_MODEL}"):
        _transcribe_locally(monkeypatch, AudioConfig(), captured)
    assert captured == {}


def test_explicit_tier_missing_is_never_swapped(monkeypatch, cache_root):
    """显式档位缺失照旧报错：不静默换成别的模型，哪怕默认档就在本地。"""
    _gpu(monkeypatch, False)
    for slug in (DEFAULT_LOCAL_WHISPER_CPU_MODEL, DEFAULT_LOCAL_WHISPER_MODEL):
        cache_root(slug).mkdir(parents=True)
    captured: dict = {}
    with pytest.raises(RuntimeError, match="--model medium"):
        _transcribe_locally(monkeypatch, AudioConfig(local_whisper_model="medium"), captured)
    assert captured == {}


def test_explicit_dir_missing_is_never_swapped(monkeypatch, cache_root, tmp_path):
    """显式目录缺失照旧报错：不落到缓存目录里的默认档。"""
    cache_root(DEFAULT_LOCAL_WHISPER_MODEL).mkdir(parents=True)
    captured: dict = {}
    missing = tmp_path / "nowhere"
    with pytest.raises(RuntimeError, match="nowhere"):
        _transcribe_locally(monkeypatch, AudioConfig(local_whisper_model_dir=str(missing)), captured)
    assert captured == {}


# ==================== 部署预装脚本 / 宿主路由 与引擎同源 ====================


def _fake_yaml_config(monkeypatch, *, tier=None, device=None) -> None:
    """以最小配置对象替换全局配置单例（与宿主测试同款形态）。"""
    parsing = SimpleNamespace(
        local_whisper_model_dir="", local_whisper_model=tier,
        local_whisper_cpu_threads=1, local_whisper_device=device,
        local_whisper_compute_type=None, local_whisper_beam_size=None,
        local_whisper_vad_enabled=True,
        local_whisper_min_speech_dbfs=None,
        local_whisper_empty_result_retry_language=None,
        local_whisper_initial_prompt=None,
    )
    config = SimpleNamespace(knowledge_base=SimpleNamespace(parsing=parsing))
    monkeypatch.setattr("novamind.setting.yaml_config.get_config", lambda: config)


def _load_download_script():
    spec = importlib.util.spec_from_file_location(
        "download_faster_whisper_model",
        BACKEND_ROOT / "scripts" / "download_faster_whisper_model.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deploy_script_downloads_the_tier_the_engine_will_use(monkeypatch):
    """部署期预装与运行时同一解析——否则无 GPU 的机器会白下约 3GB 的 large-v3，
    或者运行时要的档位根本没下载。"""
    script = _load_download_script()

    _fake_yaml_config(monkeypatch)
    _gpu(monkeypatch, False)
    assert script.resolve_model_slug(None) == DEFAULT_LOCAL_WHISPER_CPU_MODEL
    assert script.describe_default_choice(None) == "（YAML 未配置档位，按推理设备自动选择：cpu）"
    _gpu(monkeypatch, True)
    assert script.resolve_model_slug(None) == DEFAULT_LOCAL_WHISPER_MODEL
    assert script.describe_default_choice(None) == "（YAML 未配置档位，按推理设备自动选择：cuda）"

    # --model 与 YAML 显式档位都优先于默认档，且不再附加「自动选择」说明
    assert script.resolve_model_slug("medium") == "medium"
    assert script.describe_default_choice("medium") == ""
    _fake_yaml_config(monkeypatch, tier="tiny")
    assert script.resolve_model_slug(None) == "tiny"
    assert script.describe_default_choice(None) == ""


def test_host_default_model_name_matches_the_engine(monkeypatch):
    """路由 / 转写日志 / 解析快照指纹使用的默认档位名 = 引擎实际会加载的档位。"""
    import novamind.features.knowledge_space.services.media_processing as mp

    _fake_yaml_config(monkeypatch)
    _gpu(monkeypatch, True)
    assert mp._resolve_default_local_asr_model() == f"faster-whisper-{DEFAULT_LOCAL_WHISPER_MODEL}"
    _gpu(monkeypatch, False)
    assert mp._resolve_default_local_asr_model() == f"faster-whisper-{DEFAULT_LOCAL_WHISPER_CPU_MODEL}"
    _fake_yaml_config(monkeypatch, tier="medium")
    assert mp._resolve_default_local_asr_model() == "faster-whisper-medium"
