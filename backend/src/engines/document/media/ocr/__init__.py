"""外部 OCR 模块：qwen3.5-ocr 统一接入（协议分发 + 归一化中间表示）。"""
from novamind.engines.document.media.ocr.blocks import (
    OcrBlock,
    OcrResult,
    bbox_from_quad,
)

__all__ = [
    "OcrBlock",
    "OcrResult",
    "bbox_from_quad",
]
