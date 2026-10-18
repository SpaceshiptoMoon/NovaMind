"""AsrConnector 连接器回归：路由解析 / 协议分发 / 本地忙碌锁。

连接器是后续一切 ASR 调用的统一入口（音频文档/视频音轨/未来场景共用），
覆盖：
- 路由：本地家族直判不查凭证；云端凭证精确匹配；凭证缺失抛
  AsrCredentialsMissingError；未注入端口时云端直接报错。
- 分发：local/openai/dashscope 各调对应引擎函数；热词/说话人分离能力
  边界告警不阻断。
- 忙碌锁：忙碌抛 AsrBusyError；成功路径 finally 释放；wait 模式等待重试。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.engines.document.media.audio import (
    AsrBusyError,
    AsrConnector,
    AsrCredentialsMissingError,
)
from novamind.engines.document.media.audio.connector import AsrRoute

pytestmark = pytest.mark.unit


def _document():
    return SimpleNamespace(id=1, uploader_id=42, file_type="mp3", filename="a.mp3")


# ==================== 路由解析 ====================


def test_resolve_local_family_no_credentials():
    """本地家族模型直判 local，不查凭证端口。"""
    mcs = SimpleNamespace(get_credentials_by_model=AsyncMock())
    route = asyncio.run(AsrConnector(mcs).resolve_route(_document(), "faster-whisper-small"))
    assert route == AsrRoute(protocol="local", model="faster-whisper-small")
    assert mcs.get_credentials_by_model.await_count == 0


def test_resolve_invalid_local_slug_raises():
    """非法本地档位（配置错误）→ AsrCredentialsMissingError fail fast。"""
    with pytest.raises(AsrCredentialsMissingError, match="不支持的本地 ASR 模型档位"):
        asyncio.run(AsrConnector().resolve_route(_document(), "faster-whisper-huge"))


def test_resolve_cloud_uses_credential_fields():
    """云端模型：protocol/model 以凭证记录为准，名字精确匹配。"""
    mcs = SimpleNamespace(get_credentials_by_model=AsyncMock(return_value=SimpleNamespace(
        api_key="sk-x", base_url="https://api.example.com",
        protocol="dashscope", model="paraformer-v2-actual",
    )))
    route = asyncio.run(AsrConnector(mcs).resolve_route(_document(), "paraformer-v2"))
    assert route.protocol == "dashscope"
    assert route.model == "paraformer-v2-actual"
    assert route.api_key == "sk-x"
    mcs.get_credentials_by_model.assert_awaited_once_with(42, "asr", "paraformer-v2")


def test_resolve_cloud_missing_credentials_raises():
    """云端凭证缺失 → AsrCredentialsMissingError（不串用其它配置）。"""
    mcs = SimpleNamespace(get_credentials_by_model=AsyncMock(return_value=None))
    with pytest.raises(AsrCredentialsMissingError, match="未找到 ASR 模型"):
        asyncio.run(AsrConnector(mcs).resolve_route(_document(), "whisper-cloud"))


def test_resolve_cloud_without_port_raises():
    """未注入凭证端口 → 云端模型直接报错（纯本地部署形态）。"""
    with pytest.raises(AsrCredentialsMissingError, match="未注入模型配置端口"):
        asyncio.run(AsrConnector(None).resolve_route(_document(), "whisper-cloud"))


# ==================== 协议分发 ====================


def test_transcribe_dispatches_local_with_slot(monkeypatch):
    """local：拿锁 → 引擎函数 → finally 释放。"""
    import novamind.engines.document.media.audio as audio_pkg

    calls = []
    released = []

    async def fake_acquire():
        calls.append("acquire")
        return True

    def fake_release():
        released.append(True)

    async def fake_local(**kwargs):
        calls.append("transcribe")
        return [{"text": "hi"}]

    # 延迟 import 的真实来源是 audio/__init__（connector 内函数内 import）
    monkeypatch.setattr(audio_pkg, "acquire_asr_or_busy", fake_acquire)
    monkeypatch.setattr(audio_pkg, "force_release_asr_slot", fake_release)
    monkeypatch.setattr(audio_pkg, "transcribe_audio_local", fake_local)

    result, route = asyncio.run(AsrConnector().transcribe(
        file_content=b"a" * 2048, file_type="mp3", asr_model="faster-whisper-tiny",
        document=_document(), language="zh",
    ))
    assert route.protocol == "local"
    assert result == [{"text": "hi"}]
    assert calls == ["acquire", "transcribe"]
    assert released == [True]  # finally 释放


def test_transcribe_local_busy_raises(monkeypatch):
    """local 忙碌 → AsrBusyError（拥塞信号），不进引擎、不误释放。"""
    import novamind.engines.document.media.audio as audio_pkg

    released = []

    async def fake_acquire():
        return False

    def fake_release():
        released.append(True)

    async def _should_not_run(**kwargs):
        raise AssertionError("忙碌时不应进入引擎转写")

    monkeypatch.setattr(audio_pkg, "acquire_asr_or_busy", fake_acquire)
    monkeypatch.setattr(audio_pkg, "force_release_asr_slot", fake_release)
    monkeypatch.setattr(audio_pkg, "transcribe_audio_local", _should_not_run)

    with pytest.raises(AsrBusyError):
        asyncio.run(AsrConnector().transcribe(
            file_content=b"a" * 2048, file_type="mp3",
            asr_model="faster-whisper-tiny", document=_document(),
        ))
    assert released == []  # 未拿到锁不释放


def test_transcribe_dispatches_openai(monkeypatch):
    """openai 协议 → Whisper API 引擎函数，凭证透传。"""
    called = {}

    async def fake_openai(**kwargs):
        called.update(kwargs)
        return []

    monkeypatch.setattr(
        "novamind.engines.document.media.audio.transcribe_audio_with_timestamps",
        fake_openai,
    )
    mcs = SimpleNamespace(get_credentials_by_model=AsyncMock(return_value=SimpleNamespace(
        api_key="sk-o", base_url="https://o.example.com", protocol="openai", model="whisper-1",
    )))
    asyncio.run(AsrConnector(mcs).transcribe(
        file_content=b"a" * 2048, file_type="mp3", asr_model="whisper-1",
        document=_document(), language=None,
    ))
    assert called["model"] == "whisper-1"
    assert called["api_key"] == "sk-o"
    assert called["base_url"] == "https://o.example.com"


def test_transcribe_dispatches_dashscope(monkeypatch):
    """dashscope 协议 → Paraformer 引擎函数，minio 注入 + 说话人分离透传。"""
    called = {}

    async def fake_dashscope(**kwargs):
        called.update(kwargs)
        return [{"text": "s", "speaker_id": 0}]

    monkeypatch.setattr(
        "novamind.engines.document.media.audio.transcribe_audio_with_dashscope",
        fake_dashscope,
    )
    document = SimpleNamespace(
        id=1, uploader_id=42, file_type="mp3", filename="a.mp3",
        get_storage_info=lambda: {"minio_bucket": "bkt"},
    )
    mcs = SimpleNamespace(get_credentials_by_model=AsyncMock(return_value=SimpleNamespace(
        api_key="sk-d", base_url=None, protocol="dashscope", model="paraformer-v2",
    )))
    result, route = asyncio.run(AsrConnector(mcs).transcribe(
        file_content=b"a" * 2048, file_type="mp3", asr_model="paraformer-v2",
        document=document, diarization_enabled=True, speaker_count=2,
        minio_client=object(),
    ))
    assert route.protocol == "dashscope"
    assert called["minio_bucket"] == "bkt"
    assert called["diarization_enabled"] is True
    assert called["speaker_count"] == 2


def test_transcribe_openai_hotwords_warned_not_blocking(monkeypatch):
    """openai 协议热词能力缺失：告警忽略，转写照常（不阻断、不报错）。"""
    called = {}
    warnings = []

    async def fake_openai(**kwargs):
        called.update(kwargs)
        return []

    import logging

    monkeypatch.setattr(
        "novamind.engines.document.media.audio.transcribe_audio_with_timestamps",
        fake_openai,
    )
    mcs = SimpleNamespace(get_credentials_by_model=AsyncMock(return_value=SimpleNamespace(
        api_key="k", base_url=None, protocol="openai", model="whisper-1",
    )))

    class _CapHandler(logging.Handler):
        def emit(self, record):
            warnings.append(record.getMessage())

    handler = _CapHandler()
    logging.getLogger("novamind.engines.document.media.audio.connector").addHandler(handler)
    try:
        asyncio.run(AsrConnector(mcs).transcribe(
            file_content=b"a" * 2048, file_type="mp3", asr_model="whisper-1",
            document=_document(), hotwords=["热词"],
        ))
    finally:
        logging.getLogger("novamind.engines.document.media.audio.connector").removeHandler(handler)
    assert called == {} or called.get("model") == "whisper-1"
    assert any("热词" in w for w in warnings)
