"""ASR 协议客户端（R3 模型客户端中心成员）。

- ``dashscope_client``：DashScope Paraformer 协议胶水（提交/轮询/解析唯一实现），
  消费方：engines/document/media/audio/audio_utils、connection_testers/asr.py

ASR 三协议的转写实现本体（local faster-whisper / openai-whisper httpx /
dashscope）仍在 ``engines/document/media/audio/audio_utils``——其中 local 路径
绑定 ASR 专用单线程 executor 隔离（d01f219），不宜搬动；本包只收协议胶水与
连通测试。
"""
from novamind.shared.ai_models.asr.dashscope_client import (
    DashScopeTranscriptionError,
    await_transcription,
    configure_dashscope,
    extract_segments,
    submit_transcription,
)

__all__ = [
    "DashScopeTranscriptionError",
    "configure_dashscope",
    "submit_transcription",
    "await_transcription",
    "extract_segments",
]
