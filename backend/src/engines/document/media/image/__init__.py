"""图像处理模块（占位——实际图像理解经 VLM 描述 + 文本 embedding，参见 engines/document/media/vlm/）。"""
from novamind.engines.document.media.vlm import (
    build_image_data_url,
    build_vlm_image_messages,
    generate_vlm_text_with_fallback,
)

__all__ = [
    "build_image_data_url",
    "build_vlm_image_messages",
    "generate_vlm_text_with_fallback",
]
