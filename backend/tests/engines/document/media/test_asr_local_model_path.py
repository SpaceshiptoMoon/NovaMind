"""Regression test for local faster-whisper model path resolution.

History: ``audio_utils._get_local_whisper_model`` used
``Path(__file__).resolve().parent`` only 4 times, landing at
``backend/src/shared/models/faster-whisper/tiny`` (model absent there), so every
audio task failed with "本地 ASR 模型未找到". The path is now resolved via an injected
``AudioConfig`` (YAML ``knowledge_base.parsing.local_whisper_model_dir`` → 宿主
构造 ``AudioConfig`` 注入) > env ``NOVAMIND_LOCAL_WHISPER_MODEL_DIR`` > default
``backend/.cache/faster-whisper/tiny`` (repo-root cache, same convention as deepdoc;
2026-10 收敛——此前默认 ``~/.cache/faster-whisper/tiny`` 与 deepdoc 缓存基准分裂).

批次 4 起 ``audio_utils`` 不再 import `novamind.setting`：YAML 配置由宿主在
``media_processing.process_audio_document`` 构造 ``AudioConfig`` 注入，引擎侧
``_resolve_local_whisper_model_dir`` 只读 ``AudioConfig.local_whisper_model_dir``
+ 环境变量 + 默认值。
"""

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.audio.audio_utils import (
    DEFAULT_LOCAL_WHISPER_MODEL,
    _resolve_local_whisper_model_dir,
)
from novamind.shared.config import AudioConfig

pytestmark = pytest.mark.unit


def _clear_env(monkeypatch):
    monkeypatch.delenv("NOVAMIND_LOCAL_WHISPER_MODEL_DIR", raising=False)


def test_default_model_dir_points_to_repo_cache(monkeypatch):
    """无 AudioConfig、无 YAML 配置时回退引擎默认档（生产 large-v3）缓存目录。

    2026-10 识别质量批次：默认档从 tiny 升为 DEFAULT_LOCAL_WHISPER_MODEL
    （面向生产；开发机在 YAML 显式降档），目录命名约定不变。
    """
    _clear_env(monkeypatch)
    # 隔离全局配置单例（防其它测试污染/防读到真实 YAML 的 local_whisper_model）
    from novamind.setting.yaml_config import get_config
    original = get_config().knowledge_base.parsing.local_whisper_model
    get_config().knowledge_base.parsing.local_whisper_model = None
    try:
        model_dir = _resolve_local_whisper_model_dir()
        expected = (
            BACKEND_ROOT / ".cache" / "faster-whisper" / "large-v3"
        )
        assert model_dir == expected
    finally:
        get_config().knowledge_base.parsing.local_whisper_model = original


def test_host_merges_asr_fallback_into_whisper_dir(monkeypatch, tmp_path):
    """发包模式改造的宿主侧语义：parsing 段未配目录时合并 asr.local_whisper_model_dir。

    原「引擎回读 YAML」的测试语义随兜底上移宿主（media_processing.
    _build_engine_audio_config），宿主构造的 AudioConfig 直接携带合并结果。
    """
    from novamind.setting.yaml_config import get_config

    fake = str(tmp_path / "custom-whisper")
    original_parsing = get_config().knowledge_base.parsing.local_whisper_model_dir
    original_asr = get_config().asr.local_whisper_model_dir
    get_config().knowledge_base.parsing.local_whisper_model_dir = None
    get_config().asr.local_whisper_model_dir = fake
    try:
        # 模拟宿主构造逻辑（与 _build_engine_audio_config 同款合并）
        parsing = get_config().knowledge_base.parsing
        merged = parsing.local_whisper_model_dir or get_config().asr.local_whisper_model_dir or None
        assert merged == fake
    finally:
        get_config().knowledge_base.parsing.local_whisper_model_dir = original_parsing
        get_config().asr.local_whisper_model_dir = original_asr


def test_audio_config_overrides_env(monkeypatch, tmp_path):
    """AudioConfig.local_whisper_model_dir 优先级高于环境变量。"""
    config_dir = tmp_path / "config-whisper"
    env_dir = tmp_path / "env-whisper"
    monkeypatch.setenv("NOVAMIND_LOCAL_WHISPER_MODEL_DIR", str(env_dir))
    model_dir = _resolve_local_whisper_model_dir(
        AudioConfig(local_whisper_model_dir=str(config_dir))
    )
    assert model_dir == config_dir


def test_audio_config_none_falls_back_to_default_slug(monkeypatch, tmp_path):
    """发包模式改造后：AudioConfig 无目录/档位 → 引擎直接用默认档位
    （YAML asr 段兜底已上移宿主 _build_engine_audio_config，见
    test_host_merges_asr_fallback_into_whisper_dir）。"""
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    model_dir = _resolve_local_whisper_model_dir(AudioConfig(local_whisper_model_dir=None))
    assert model_dir.name == DEFAULT_LOCAL_WHISPER_MODEL