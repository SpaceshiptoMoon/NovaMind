"""VLM（视觉语言模型）模块，为多模态内容生成文本描述供 embedding 使用。"""
from novamind.engines.document.media.vlm.vlm_utils import (
    build_image_data_url,
    build_vlm_image_messages,
    build_vlm_multi_image_messages,
    generate_vlm_text_with_fallback,
)

__all__ = [
    "build_image_data_url",
    "build_vlm_image_messages",
    "build_vlm_multi_image_messages",
    "generate_vlm_text_with_fallback",
]
