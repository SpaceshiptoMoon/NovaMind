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


def test_env_var_overrides_default(monkeypatch, tmp_path):
    """asr.local_whisper_model_dir（配置中心，值可来自 env 占位）覆盖默认路径。"""
    _clear_env(monkeypatch)
    fake = tmp_path / "custom-whisper"
    from novamind.setting.yaml_config import get_config
    original = get_config().asr.local_whisper_model_dir
    get_config().asr.local_whisper_model_dir = str(fake)
    try:
        model_dir = _resolve_local_whisper_model_dir()
        assert model_dir == fake
    finally:
        get_config().asr.local_whisper_model_dir = original


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
    """AudioConfig.local_whisper_model_dir 为 None 时回退 asr.local_whisper_model_dir。"""
    env_dir = tmp_path / "env-whisper"
    from novamind.setting.yaml_config import get_config
    original = get_config().asr.local_whisper_model_dir
    get_config().asr.local_whisper_model_dir = str(env_dir)
    try:
        model_dir = _resolve_local_whisper_model_dir(
            AudioConfig(local_whisper_model_dir=None)
        )
        assert model_dir == env_dir
    finally:
        get_config().asr.local_whisper_model_dir = original