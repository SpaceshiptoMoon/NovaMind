"""多模态媒体处理模块（音频 / 视频 / VLM / 图像）。"""
from novamind.engines.document.media.audio import (
    _asr_busy_lock,
    acquire_asr_or_busy,
    is_local_asr_busy,
    transcribe_audio_local,
    transcribe_audio_with_dashscope,
    transcribe_audio_with_timestamps,
    upload_parsed_text_to_minio,
)
from novamind.engines.document.media.chunk_time_alignment import (
    align_chunk_times,
    build_frame_timeline_map,
    build_segment_timeline_map,
    format_time_anchor,
)
from novamind.engines.document.media.video import extract_video_frames
from novamind.engines.document.media.vlm import (
    build_image_data_url,
    build_vlm_image_messages,
    generate_vlm_text_with_fallback,
)

__all__ = [
    "_asr_busy_lock",
    "acquire_asr_or_busy",
    "extract_video_frames",
    "is_local_asr_busy",
    "transcribe_audio_local",
    "transcribe_audio_with_dashscope",
    "transcribe_audio_with_timestamps",
    "upload_parsed_text_to_minio",
    "build_image_data_url",
    "build_vlm_image_messages",
    "generate_vlm_text_with_fallback",
    "align_chunk_times",
    "build_frame_timeline_map",
    "build_segment_timeline_map",
    "format_time_anchor",
]
