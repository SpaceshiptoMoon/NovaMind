"""外部 OCR 模块：qwen3.5-ocr 统一接入（协议分发 + 归一化中间表示）。"""
from novamind.engines.document.media.ocr.blocks import (
    OcrBlock,
    OcrResult,
    bbox_from_quad,
)
from novamind.engines.document.media.ocr.connector import (
    OcrConnector,
    OcrCredentialsMissingError,
    OcrRoute,
)
from novamind.engines.document.media.ocr.qwen import (
    MIME_BY_EXT,
    OcrEngineConfig,
    OcrFileInvalidError,
    OcrRequestError,
    parse_document_with_qwen_ocr,
    recognize_image_with_qwen_ocr,
    render_pdf_page_images,
)

__all__ = [
    "MIME_BY_EXT",
    "OcrBlock",
    "OcrConnector",
    "OcrCredentialsMissingError",
    "OcrEngineConfig",
    "OcrFileInvalidError",
    "OcrRequestError",
    "OcrResult",
    "OcrRoute",
    "bbox_from_quad",
    "parse_document_with_qwen_ocr",
    "recognize_image_with_qwen_ocr",
    "render_pdf_page_images",
]
