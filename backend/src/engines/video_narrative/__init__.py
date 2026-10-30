"""视频叙事合成引擎：碎片块描述 → 章节化连贯叙事文档（Map-Reduce 两层）。"""
from novamind.engines.video_narrative.service import (
    NarrativeBlock,
    NarrativeChapter,
    NarrativeDocument,
    NarrativeSynthesisError,
    VideoNarrativeSynthesizer,
)

__all__ = [
    "NarrativeBlock",
    "NarrativeChapter",
    "NarrativeDocument",
    "NarrativeSynthesisError",
    "VideoNarrativeSynthesizer",
]
