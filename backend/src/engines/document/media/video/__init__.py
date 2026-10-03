"""视频处理模块：帧提取（固定间隔 / 场景切换）+ 帧去重 + 帧描述（single/grouped/rewrite）。
每类帧提取均提供 bytes 与 *_from_path 两种入口；路径版供大文件管道（worker 落盘后直传路径）。
"""
from novamind.engines.document.media.video.frame_dedup import (
    dedup_embedding,
    dedup_frame_diff,
    dedup_none,
)
from novamind.engines.document.media.video.frame_description import (
    AllFrameDescriptionsFailedError,
    describe_grouped,
    describe_rewrite,
    describe_single,
)
from novamind.engines.document.media.video.frame_extraction import (
    extract_frames_fixed,
    extract_frames_fixed_from_path,
    extract_frames_scene,
    extract_frames_scene_from_path,
)
from novamind.engines.document.media.video.video_utils import extract_video_frames

__all__ = [
    "extract_video_frames",
    "extract_frames_fixed",
    "extract_frames_fixed_from_path",
    "extract_frames_scene",
    "extract_frames_scene_from_path",
    "dedup_none",
    "dedup_frame_diff",
    "dedup_embedding",
    "describe_single",
    "describe_grouped",
    "describe_rewrite",
    "AllFrameDescriptionsFailedError",
]