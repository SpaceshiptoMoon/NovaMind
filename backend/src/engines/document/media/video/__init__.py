"""视频处理模块：帧提取（固定间隔 / 场景切换）+ 帧去重 + 帧描述（single/grouped/rewrite）。"""
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
    extract_frames_scene,
)
from novamind.engines.document.media.video.video_utils import extract_video_frames

__all__ = [
    "extract_video_frames",
    "extract_frames_fixed",
    "extract_frames_scene",
    "dedup_none",
    "dedup_frame_diff",
    "dedup_embedding",
    "describe_single",
    "describe_grouped",
    "describe_rewrite",
    "AllFrameDescriptionsFailedError",
]