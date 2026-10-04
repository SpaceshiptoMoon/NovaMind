"""音频处理模块。"""
from novamind.engines.document.media.audio.audio_utils import (
    AudioFileInvalidError,
    DEFAULT_LOCAL_WHISPER_MODEL,
    LOCAL_WHISPER_SUPPORTED_MODELS,
    acquire_asr_or_busy,
    default_faster_whisper_cache_dir,
    force_release_asr_slot,
    is_local_asr_busy,
    split_local_whisper_model_name,
    transcribe_audio_local,
    transcribe_audio_with_dashscope,
    transcribe_audio_with_timestamps,
    upload_parsed_text_to_minio,
)

__all__ = [
    "AudioFileInvalidError",
    "DEFAULT_LOCAL_WHISPER_MODEL",
    "LOCAL_WHISPER_SUPPORTED_MODELS",
    "acquire_asr_or_busy",
    "default_faster_whisper_cache_dir",
    "force_release_asr_slot",
    "is_local_asr_busy",
    "split_local_whisper_model_name",
    "transcribe_audio_local",
    "transcribe_audio_with_dashscope",
    "transcribe_audio_with_timestamps",
    "upload_parsed_text_to_minio",
]
