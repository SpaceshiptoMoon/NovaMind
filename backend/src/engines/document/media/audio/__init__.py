"""音频处理模块。"""
from novamind.engines.document.media.audio.audio_utils import (
    AudioFileInvalidError,
    _asr_busy_lock,  # noqa: F401 向下 re-export（任务4.4 收口后删除）
    acquire_asr_or_busy,
    is_local_asr_busy,
    transcribe_audio_local,
    transcribe_audio_with_dashscope,
    transcribe_audio_with_timestamps,
    upload_parsed_text_to_minio,
)

__all__ = [
    "AudioFileInvalidError",
    "acquire_asr_or_busy",
    "is_local_asr_busy",
    "transcribe_audio_local",
    "transcribe_audio_with_dashscope",
    "transcribe_audio_with_timestamps",
    "upload_parsed_text_to_minio",
]
