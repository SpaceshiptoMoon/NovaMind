"""DeepDoc 纯文本 PDF 解析器：无 OCR / 无版面分析，仅提取原始文本。"""
from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/pdf_parser.py:PlainParser
from io import BytesIO
from pathlib import Path

import pdfplumber

# 与 pdf.py 共用同一把锁（见 _pdfplumber_sync 模块注释）
from novamind.engines.document.integrations.deepdoc.parsers._pdfplumber_sync import (
    _pdfplumber_lock,
)
from novamind.engines.document.integrations.deepdoc.parsers.upstream.utils import (
    extract_pdf_outlines,
)
from novamind.shared.logging import get_logger
from novamind.shared.utils.text_utils import normalize_pua_text

logger = get_logger(__name__)


class RAGFlowPlainPdfParser:
    """无 OCR 的轻量 PDF 解析器：pdfplumber 直抽文本，深度档不可用时的降级路径。"""
    def __call__(
        self,
        filename: str | bytes | Path,
        from_page: int = 0,
        to_page: int | None = None,
    ):
        """按页抽取 PDF 文本流并做 PUA 归一。

        Returns:
            (lines, tables, outlines) 三元组：lines 为（归一后文本行，页码空串）列表，
            tables 恒为空列表，outlines 为 PDF 书签标题。
        """
        lines = []
        outlines = extract_pdf_outlines(filename)
        try:
            pdf_source = str(filename) if not isinstance(filename, bytes) else BytesIO(filename)
            with _pdfplumber_lock, pdfplumber.open(pdf_source) as pdf:
                end_page = len(pdf.pages) if to_page is None else min(len(pdf.pages), to_page)
                for page in pdf.pages[from_page:end_page]:
                    text = page.extract_text() or ""
                    # 逐行 PUA 归一（语境化规则与 full 模式/通用 reader 共用）：
                    # plain 路径的全文与 chunks 全部来自这些 line，无第二出口。
                    # 邻居判定天然限制在行内，与 replace_pua 的单字符串语义一致。
                    lines.extend(
                        normalize_pua_text(line) for line in text.split("\n")
                    )
        except Exception:
            logger.exception("DeepDoc plain pdf parser failed")
        return [(line, "") for line in lines], [], outlines
