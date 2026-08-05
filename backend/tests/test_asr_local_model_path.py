"""Regression test for local faster-whisper model path resolution.

History: ``audio_utils._get_local_whisper_model`` used
``Path(__file__).resolve().parent`` only 4 times, landing at
``backend/src/shared/models/faster-whisper/tiny`` (model absent there), so every
audio task failed with "本地 ASR 模型未找到". The real model lives at
``~/.cache/faster-whisper/tiny``. The path is now resolved via an injected
``AudioConfig`` (YAML ``knowledge_base.parsing.local_whisper_model_dir`` → 宿主
构造 ``AudioConfig`` 注入) > env ``NOVAMIND_LOCAL_WHISPER_MODEL_DIR`` > default
``~/.cache/faster-whisper/tiny``.

批次 4 起 ``audio_utils`` 不再 import `novamind.setting`：YAML 配置由宿主在
``media_processing.process_audio_document`` 构造 ``AudioConfig`` 注入，引擎侧
``_resolve_local_whisper_model_dir`` 只读 ``AudioConfig.local_whisper_model_dir``
+ 环境变量 + 默认值。
"""

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.config import AudioConfig
from novamind.features.knowledge_space.media.audio.audio_utils import (
    _resolve_local_whisper_model_dir,
)

pytestmark = pytest.mark.unit


def _clear_env(monkeypatch):
    monkeypatch.delenv("NOVAMIND_LOCAL_WHISPER_MODEL_DIR", raising=False)


def test_default_model_dir_points_to_user_cache(monkeypatch):
    """无 AudioConfig、无环境变量时回退默认 ~/.cache/faster-whisper/tiny。"""
    _clear_env(monkeypatch)
    model_dir = _resolve_local_whisper_model_dir()
    assert model_dir == Path.home() / ".cache" / "faster-whisper" / "tiny"
    # 模型实际存在于该默认目录
    assert (model_dir / "model.bin").exists(), f"model.bin missing at {model_dir}"


def test_env_var_overrides_default(monkeypatch, tmp_path):
    """NOVAMIND_LOCAL_WHISPER_MODEL_DIR 必须覆盖默认路径。"""
    _clear_env(monkeypatch)
    fake = tmp_path / "custom-whisper"
    monkeypatch.setenv("NOVAMIND_LOCAL_WHISPER_MODEL_DIR", str(fake))
    model_dir = _resolve_local_whisper_model_dir()
    assert model_dir == fake


def test_audio_config_overrides_env(monkeypatch, tmp_path):
    """AudioConfig.local_whisper_model_dir 优先级高于环境变量。"""
    config_dir = tmp_path / "config-whisper"
    env_dir = tmp_path / "env-whisper"
    monkeypatch.setenv("NOVAMIND_LOCAL_WHISPER_MODEL_DIR", str(env_dir))
    model_dir = _resolve_local_whisper_model_dir(
        AudioConfig(local_whisper_model_dir=str(config_dir))
    )
    assert model_dir == config_dir


def test_audio_config_none_falls_back_to_env(monkeypatch, tmp_path):
    """AudioConfig.local_whisper_model_dir 为 None 时回退到环境变量。"""
    env_dir = tmp_path / "env-whisper"
    monkeypatch.setenv("NOVAMIND_LOCAL_WHISPER_MODEL_DIR", str(env_dir))
    model_dir = _resolve_local_whisper_model_dir(
        AudioConfig(local_whisper_model_dir=None)
    )
    assert model_dir == env_dir