"""音频处理模块。"""
from novamind.engines.document.media.audio.audio_utils import (
    DEFAULT_LOCAL_WHISPER_MODEL,
    LOCAL_WHISPER_SUPPORTED_MODELS,
    AudioFileInvalidError,
    acquire_asr_or_busy,
    default_faster_whisper_cache_dir,
    finalize_segment_meta,
    force_release_asr_slot,
    release_asr_slot,
    group_transcript_segments,
    is_local_asr_busy,
    merge_segment_meta,
    sigmoid_confidence,
    split_local_whisper_model_name,
    transcribe_audio_local,
    transcribe_audio_with_dashscope,
    transcribe_audio_with_timestamps,
    upload_parsed_text_to_minio,
)
from novamind.engines.document.media.audio.clip_extractor import (
    AudioClipExtractionError,
    extract_audio_clip,
)
from novamind.engines.document.media.audio.connector import (
    AsrBusyError,
    AsrConnector,
    AsrCredentialsMissingError,
    AsrRoute,
)
from novamind.engines.document.media.audio.evaluation import (
    cer,
    evaluate_transcript,
    wer,
)

__all__ = [
    "AsrBusyError",
    "AsrConnector",
    "AsrCredentialsMissingError",
    "AsrRoute",
    "AudioClipExtractionError",
    "AudioFileInvalidError",
    "DEFAULT_LOCAL_WHISPER_MODEL",
    "LOCAL_WHISPER_SUPPORTED_MODELS",
    "acquire_asr_or_busy",
    "cer",
    "default_faster_whisper_cache_dir",
    "evaluate_transcript",
    "extract_audio_clip",
    "finalize_segment_meta",
    "force_release_asr_slot",
    "release_asr_slot",
    "group_transcript_segments",
    "is_local_asr_busy",
    "merge_segment_meta",
    "sigmoid_confidence",
    "split_local_whisper_model_name",
    "transcribe_audio_local",
    "transcribe_audio_with_dashscope",
    "transcribe_audio_with_timestamps",
    "upload_parsed_text_to_minio",
    "wer",
]
