"""ASR 协议客户端包（DashScope 胶水与连通测试）。

三协议转写本体留在 audio_utils——local 路径绑定 ASR 专用单线程 executor 隔离，不宜搬动。
"""
from novamind.shared.ai_models.asr.dashscope_client import (
    TRANSCRIPTION_WAIT_TIMEOUT_SECONDS,
    DashScopeTranscriptionError,
    await_transcription,
    await_transcription_async,
    configure_dashscope,
    extract_segments,
    submit_transcription,
)

__all__ = [
    "DashScopeTranscriptionError",
    "TRANSCRIPTION_WAIT_TIMEOUT_SECONDS",
    "configure_dashscope",
    "submit_transcription",
    "await_transcription",
    "await_transcription_async",
    "extract_segments",
]
