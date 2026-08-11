"""音频文件永久性错误不回退云端 ASR 的回归测试。

History: document 60（06_podcast.m4a，486 字节损坏文件）本地 ASR 因 ``MIN_AUDIO_SIZE``
拦截抛 ``ValueError``，``media_processing`` 无差别 catch 后回退云端 DashScope，云端又因
MinIO 公网 URL 不可达抛 ``FILE_DOWNLOAD_FAILED``，把「文件损坏」这个永久性根因藏到三层
错误之后，用户排查多轮才定位。

Fix: 引擎层新增 ``AudioFileInvalidError(ValueError)`` 标识文件本身无效（过小/损坏/格式
不支持/解码失败）——这类错误回退云端也救不了。``media_processing`` catch 时
``isinstance`` 判断，永久性错误直接抛 ``DocumentProcessingError`` 引导用户重新上传，
不回退云端；瞬时性错误（模型未找到 ``RuntimeError``、子进程崩溃 ``BrokenProcessPool``）
仍走云端回退。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.media.audio import AudioFileInvalidError
from novamind.engines.document.media.audio import audio_utils
from novamind.features.knowledge_space.exceptions import DocumentProcessingError
from novamind.features.knowledge_space.services import media_processing

pytestmark = pytest.mark.unit


# ---------- 1. audio_utils 层：永久性错误抛 AudioFileInvalidError ----------


def test_audio_file_invalid_error_is_value_error_subclass():
    """AudioFileInvalidError 必须是 ValueError 子类，保持向后兼容（旧代码 catch ValueError）。"""
    assert issubclass(AudioFileInvalidError, ValueError)
    exc = AudioFileInvalidError("x")
    assert isinstance(exc, ValueError)


@pytest.mark.asyncio
async def test_transcribe_local_too_small_raises_audio_file_invalid():
    """过小文件（< MIN_AUDIO_SIZE=1024）抛 AudioFileInvalidError，不是普通 ValueError。

    复现 document 60 场景：486 字节 m4a。用 RIFF magic 头构造小 wav，过格式校验后
    被 MIN_AUDIO_SIZE 拦截。
    """
    # RIFF 头让 _detect_audio_format 识别为 wav（过格式校验），但总长 < 1024 被拦截
    small_wav = b"RIFF" + b"\x00" * 100  # 104 bytes
    with pytest.raises(AudioFileInvalidError, match="音频文件过小"):
        await audio_utils.transcribe_audio_local(
            file_content=small_wav, file_type="wav", language=None, audio_config=None,
        )


@pytest.mark.asyncio
async def test_transcribe_local_empty_raises_audio_file_invalid():
    """空/极小文件（< 12 bytes）抛 AudioFileInvalidError。"""
    with pytest.raises(AudioFileInvalidError, match="音频文件太小或为空"):
        await audio_utils.transcribe_audio_local(
            file_content=b"\x00" * 5, file_type="mp3", language=None, audio_config=None,
        )


# ---------- 2. media_processing 层：永久性错误不回退云端 ----------


@pytest.mark.asyncio
async def test_process_audio_does_not_fallback_cloud_on_invalid_file(monkeypatch):
    """本地 ASR 抛 AudioFileInvalidError 时不回退云端，直接抛 DocumentProcessingError。

    回归 document 60：损坏文件不应走到云端 DashScope 又报 FILE_DOWNLOAD_FAILED，
    而应第一时间抛「音频文件损坏，请重新上传」。
    """
    # mock load_pipeline_context：绕过 DB，返回最小 ctx
    async def _fake_load_ctx(session, document, task=None):
        return SimpleNamespace(
            pipeline_config={"parsing": {"audio": {}}},
            space=SimpleNamespace(config={}),
        )

    monkeypatch.setattr(media_processing, "load_pipeline_context", _fake_load_ctx)

    # mock get_config：绕过 YAML 加载
    monkeypatch.setattr(
        "novamind.setting.yaml_config.get_config",
        lambda: SimpleNamespace(
            knowledge_base=SimpleNamespace(
                parsing=SimpleNamespace(
                    local_whisper_model_dir=str(Path.home() / ".cache" / "faster-whisper" / "tiny"),
                    local_whisper_cpu_threads=1,
                )
            )
        ),
    )

    # mock ASR 凭证：protocol=local → 进本地 ASR 分支
    mcs = SimpleNamespace()
    mcs.repo = SimpleNamespace()
    async def _fake_get_creds(uploader_id, model_type, model):
        return SimpleNamespace(protocol="local", api_key=None, base_url=None, model="faster-whisper-tiny")
    mcs.get_credentials_by_model = _fake_get_creds

    # mock 取消检查
    async def _no_cancel(doc_id):
        return None
    monkeypatch.setattr(media_processing, "_check_document_cancelled", _no_cancel)

    # mock acquire_asr_or_busy：返回 True（拿到锁，进转写分支）
    async def _acquire_true():
        return True
    monkeypatch.setattr(
        "novamind.engines.document.media.audio.acquire_asr_or_busy", _acquire_true
    )

    # mock transcribe_audio_local：抛 AudioFileInvalidError（文件损坏）
    async def _raise_invalid(*a, **kw):
        raise AudioFileInvalidError("音频文件过小 (486 bytes)，本地 ASR 要求至少 1024 bytes")
    monkeypatch.setattr(media_processing, "transcribe_audio_local", _raise_invalid)

    # mock _find_cloud_asr_credentials：若被调用则失败（证明不应回退云端）
    async def _cloud_should_not_be_called(*a, **kw):
        raise AssertionError("文件损坏是永久性错误，不应回退云端 ASR")
    monkeypatch.setattr(media_processing, "_find_cloud_asr_credentials", _cloud_should_not_be_called)

    document = SimpleNamespace(
        id=60, space_id=1, kb_id=1, uploader_id=1, file_type="m4a",
    )

    # structlog 风格 logger：info/warning/... 接受 (event, **kwargs)
    def _noop(*a, **k):
        pass
    fake_logger = SimpleNamespace(
        info=_noop, warning=_noop, error=_noop, debug=_noop, critical=_noop,
    )

    with pytest.raises(DocumentProcessingError) as exc_info:
        await media_processing.process_audio_document(
            document=document,
            file_content=b"\x00" * 486,
            session=None,
            logger=fake_logger,
            task=None,
            model_config_port=mcs,
        )

    # 错误信息引导用户重新上传，而不是 FILE_DOWNLOAD_FAILED
    msg = exc_info.value.error_message
    assert "损坏" in msg or "不完整" in msg, f"错误信息应指向文件损坏: {msg}"
    assert "重新上传" in msg, f"错误信息应引导重新上传: {msg}"