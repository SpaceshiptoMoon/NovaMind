"""Regression test for local faster-whisper model path resolution.

History: ``audio_utils._get_local_whisper_model`` used
``Path(__file__).resolve().parent`` only 4 times, landing at
``backend/src/shared/models/faster-whisper/tiny`` (model absent there), so every
audio task failed with "本地 ASR 模型未找到". The real model lives at
``backend/models/faster-whisper/tiny``. The path is now configurable
(YAML ``knowledge_base.parsing.local_whisper_model_dir`` > env
``NOVAMIND_LOCAL_WHISPER_MODEL_DIR`` > default ``backend/models/faster-whisper/tiny``).
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.knowledge.media_processing.audio.audio_utils import (
    _resolve_local_whisper_model_dir,
)

pytestmark = pytest.mark.unit


def _clear_env(monkeypatch):
    monkeypatch.delenv("NOVAMIND_LOCAL_WHISPER_MODEL_DIR", raising=False)


def test_default_model_dir_points_to_backend_models(monkeypatch):
    """Default resolution must land at backend/models/faster-whisper/tiny (where model.bin exists)."""
    _clear_env(monkeypatch)
    with patch("novamind.setting.get_config_value", return_value=None):
        model_dir = _resolve_local_whisper_model_dir()
    assert model_dir.name == "tiny"
    assert model_dir.parent.name == "faster-whisper"
    assert model_dir.parent.parent.name == "models"
    # parents[5] of audio_utils.py == backend/
    assert model_dir.parent.parent.parent.name == "backend"
    assert (model_dir / "model.bin").exists(), f"model.bin missing at {model_dir}"


def test_env_var_overrides_default(monkeypatch, tmp_path):
    """NOVAMIND_LOCAL_WHISPER_MODEL_DIR must override the default path."""
    fake = tmp_path / "custom-whisper"
    monkeypatch.setenv("NOVAMIND_LOCAL_WHISPER_MODEL_DIR", str(fake))
    with patch("novamind.setting.get_config_value", return_value=None):
        model_dir = _resolve_local_whisper_model_dir()
    assert model_dir == fake


def test_yaml_config_overrides_env(monkeypatch, tmp_path):
    """YAML config value must take precedence over the env var."""
    yaml_dir = tmp_path / "yaml-whisper"
    env_dir = tmp_path / "env-whisper"
    monkeypatch.setenv("NOVAMIND_LOCAL_WHISPER_MODEL_DIR", str(env_dir))
    with patch("novamind.setting.get_config_value", return_value=str(yaml_dir)):
        model_dir = _resolve_local_whisper_model_dir()
    assert model_dir == yaml_dir