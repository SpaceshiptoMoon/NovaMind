"""批2 c2 回归：ASR 路由抽取（_resolve_asr_route / _run_asr_transcription）。

抽取为模块级函数后音频/视频音轨共用同一路由。覆盖：
- 本地默认模型不查凭证（protocol=local）；
- 云端模型凭证精确匹配（protocol/model 以凭证为准）；
- 凭证缺失抛 PermanentProcessingError（no-fallback）；
- 协议分发：local/dashscope/openai 各调对应引擎函数。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
import novamind.features.knowledge_space.services.media_processing as mp
from novamind.features.knowledge_space.exceptions import PermanentProcessingError
from novamind.features.knowledge_space.services.media_processing import (
    _resolve_asr_route,
    _run_asr_transcription,
)
from novamind.shared.config import AudioConfig

pytestmark = pytest.mark.unit


def _document():
    return SimpleNamespace(id=1, uploader_id=42, file_type="mp3", filename="a.mp3")


def test_resolve_local_default_needs_no_credentials():
    """本地默认模型：protocol=local，凭证全空，不查 ModelConfigService。"""
    mcs = SimpleNamespace(get_credentials_by_model=AsyncMock())
    protocol, model, key, url = asyncio.run(
        _resolve_asr_route(_document(), mcs, "faster-whisper-tiny")
    )
    assert (protocol, model, key, url) == ("local", "faster-whisper-tiny", None, None)
    assert mcs.get_credentials_by_model.await_count == 0


def test_resolve_cloud_model_uses_credential_fields():
    """云端模型：protocol/model 以实际凭证为准。"""
    mcs = SimpleNamespace(get_credentials_by_model=AsyncMock(return_value=SimpleNamespace(
        api_key="sk-x", base_url="https://api.example.com", protocol="dashscope",
        model="paraformer-v2-actual",
    )))
    protocol, model, key, url = asyncio.run(
        _resolve_asr_route(_document(), mcs, "paraformer-v2")
    )
    assert protocol == "dashscope"
    assert model == "paraformer-v2-actual"
    assert key == "sk-x"
    assert url == "https://api.example.com"
    mcs.get_credentials_by_model.assert_awaited_once_with(42, "asr", "paraformer-v2")


def test_resolve_missing_credentials_raises_permanent():
    """云端凭证缺失：PermanentProcessingError（不串用其它配置）。"""
    mcs = SimpleNamespace(get_credentials_by_model=AsyncMock(return_value=None))
    with pytest.raises(PermanentProcessingError, match="未找到 ASR 模型"):
        asyncio.run(_resolve_asr_route(_document(), mcs, "whisper-cloud"))


def test_run_asr_dispatches_local(monkeypatch):
    """协议分发：local → transcribe_audio_local（收 AudioConfig 注入）。"""
    called = {}

    async def fake_local(**kwargs):
        called.update(kwargs)
        return [{"start": 0.0, "text": "hi"}]

    monkeypatch.setattr(mp, "transcribe_audio_local", fake_local)
    audio_cfg = AudioConfig(local_whisper_model_dir="/models/w")
    result = asyncio.run(_run_asr_transcription(
        file_content=b"audio-bytes", file_type="mp3", protocol="local",
        model="faster-whisper-tiny", api_key=None, base_url=None,
        language="zh", engine_audio_config=audio_cfg, document=_document(),
    ))
    assert result == [{"start": 0.0, "text": "hi"}]
    assert called["file_content"] == b"audio-bytes"
    assert called["audio_config"] is audio_cfg


def test_run_asr_dispatches_openai(monkeypatch):
    """协议分发：openai → transcribe_audio_with_timestamps。"""
    called = {}

    async def fake_openai(**kwargs):
        called.update(kwargs)
        return []

    monkeypatch.setattr(mp, "transcribe_audio_with_timestamps", fake_openai)
    asyncio.run(_run_asr_transcription(
        file_content=b"audio-bytes", file_type="mp3", protocol="openai",
        model="whisper-1", api_key="sk-x", base_url=None,
        language=None, engine_audio_config=AudioConfig(), document=_document(),
    ))
    assert called["model"] == "whisper-1"
    assert called["api_key"] == "sk-x"
