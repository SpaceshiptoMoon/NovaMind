"""文档格式转换器模块（旧版 .doc 在线迁移等）。"""
from novamind.engines.document.converters.doc_converter import (
    DocConversionError,
    convert_doc_to_docx,
)

__all__ = [
    "DocConversionError",
    "convert_doc_to_docx",
]
