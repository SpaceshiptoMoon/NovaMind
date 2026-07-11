from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/pdf_parser.py:PlainParser

from io import BytesIO
from pathlib import Path
from typing import Optional, Union

import pdfplumber

from src.shared.utils.deepdoc.logging_compat import get_logger
from src.shared.utils.deepdoc.ragflow_utils import extract_pdf_outlines

logger = get_logger(__name__)


class RAGFlowPlainPdfParser:
    def __call__(
        self,
        filename: Union[str, bytes, Path],
        from_page: int = 0,
        to_page: Optional[int] = None,
    ):
        lines = []
        outlines = extract_pdf_outlines(filename)
        try:
            pdf_source = str(filename) if not isinstance(filename, bytes) else BytesIO(filename)
            with pdfplumber.open(pdf_source) as pdf:
                end_page = len(pdf.pages) if to_page is None else min(len(pdf.pages), to_page)
                for page in pdf.pages[from_page:end_page]:
                    text = page.extract_text() or ""
                    lines.extend([line for line in text.split("\n")])
        except Exception:
            logger.exception("DeepDoc plain pdf parser failed")
        return [(line, "") for line in lines], [], outlines
