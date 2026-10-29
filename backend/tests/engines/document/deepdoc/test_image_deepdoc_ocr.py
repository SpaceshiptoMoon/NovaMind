"""矩阵二区：图片 deepdoc_ocr 解析（figure parser 本地 OCR 真跑）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def _vision_available() -> bool:
    """DeepDoc vision 运行时可用性（模型已缓存则 True）。"""
    try:
        from novamind.engines.document.integrations.deepdoc.vision_runtime import (
            get_vision_runtime_status,
        )
        return get_vision_runtime_status().get("available", False)
    except Exception:
        return False


requires_vision = pytest.mark.skipif(
    not _vision_available(), reason="DeepDoc vision 运行时不可用（模型未缓存）"
)


@requires_vision
class TestImageDeepdocOcr:
    def test_png_ocr_extracts_text(self, tmp_path):
        """png → deepdoc_ocr：本地 OCR 提取图中文字。"""
        import asyncio

        import fitz
        from novamind.engines.document.pipeline.document_loader import DocumentProcessor

        # 构造含文字的 png（fitz 渲染文字页为图）
        pdf = fitz.open()
        page = pdf.new_page(width=400, height=200)
        page.insert_htmlbox(fitz.Rect(20, 40, 380, 160), "<p>" + "图片OCR矩阵验证XYZQ" + "</p>")
        pix = page.get_pixmap(dpi=150)
        pix.save(str(tmp_path / "probe.png"))
        pdf.close()

        proc = DocumentProcessor(embedding_client=None)
        result = asyncio.run(proc.parse_document_result(
            tmp_path / "probe.png",
            parsing_config={"strategy": "deepdoc", "deepdoc_parser_id": "figure"},
        ))
        assert result.full_text.strip(), "OCR 全文为空"
        assert "XYZQ" in result.full_text, f"OCR 未识别标记: {result.full_text[:80]!r}"

    def test_textless_image_degrades(self, tmp_path):
        """纯色无字图 → 0 字符空产物（不崩、不幻觉）。"""
        import asyncio

        import fitz
        from novamind.engines.document.pipeline.document_loader import DocumentProcessor

        pdf = fitz.open()
        page = pdf.new_page(width=200, height=200)
        page.draw_rect(fitz.Rect(10, 10, 190, 190), color=(0, 0, 1), fill=(1, 1, 0))
        pix = page.get_pixmap(dpi=100)
        pix.save(str(tmp_path / "blank.png"))
        pdf.close()

        proc = DocumentProcessor(embedding_client=None)
        result = asyncio.run(proc.parse_document_result(
            tmp_path / "blank.png",
            parsing_config={"strategy": "deepdoc", "deepdoc_parser_id": "figure"},
        ))
        assert isinstance(result.full_text, str)
