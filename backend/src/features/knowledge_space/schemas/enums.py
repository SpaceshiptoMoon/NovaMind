"""
知识空间模块 - 领域枚举

集中定义分块类型等跨服务/检索/ES 共用的领域枚举，避免字符串硬编码散落各处。
"""

from enum import StrEnum


class ChunkType(StrEnum):
    """文档分块类型，与 ES chunk 的 chunk_type 字段对齐。"""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"