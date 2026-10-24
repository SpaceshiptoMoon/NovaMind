"""epub 文件接线回归测试（批次 1.5）。

历史状态：epub 是「半接线」格式——解析侧全链路已支持（DeepDoc epub 解析器、
schema 配置字段、TEXT_DOC_TYPES 均在），但上传白名单与 validator 识别缺失，
文件根本传不进来。本文件锁定补全后的上传链行为：

正例：真实 OCF 结构（mimetype 首条目 + application/epub+zip）通过校验。
反例：普通 zip 改名 .epub 被容器深检拒绝（防伪装能力与 docx 同级）。
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services.document_file_types import (
    MODALITY_TO_FILE_TYPES,
    SUPPORTED_FILE_TYPES,
)
from novamind.shared.document.validation.file_validator import FileValidator

pytestmark = pytest.mark.unit


def _build_epub_bytes() -> bytes:
    """构造最小合法 EPUB（OCF 容器）：mimetype 首个存储条目 + 一个内容文件。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # OCF 规范：mimetype 必须是首个条目且不压缩
        zf.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr("META-INF/container.xml", "<container/>")
        zf.writestr("content.xhtml", "<html><body>正文</body></html>")
    return buf.getvalue()


def _build_plain_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.txt", "普通 zip 内容，无 mimetype 条目")
    return buf.getvalue()


class TestWhitelist:
    def test_epub_in_supported_file_types(self):
        assert "epub" in SUPPORTED_FILE_TYPES

    def test_epub_in_text_modality(self):
        assert "epub" in MODALITY_TO_FILE_TYPES["text"]


class TestValidator:
    def test_valid_epub_passes(self):
        info = FileValidator().validate(_build_epub_bytes(), "book.epub")
        assert info.is_valid, info.validation_message
        assert info.detected_extension == "epub"

    def test_plain_zip_renamed_epub_rejected(self):
        """反例：任意 zip 改名 .epub 被深检拒绝（无 mimetype 条目）。"""
        info = FileValidator().validate(_build_plain_zip_bytes(), "fake.epub")
        assert not info.is_valid
        assert "伪装" in info.validation_message or "不匹配" in info.validation_message

    def test_epub_extension_mime_table_entry(self):
        """EXTENSION_TO_MIME 有 epub 条目——防伪装比对生效的前提。"""
        assert "epub" in FileValidator.EXTENSION_TO_MIME
