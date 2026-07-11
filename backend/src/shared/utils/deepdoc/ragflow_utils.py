from __future__ import annotations

# Adapted from RAGFlow deepdoc/parser/utils.py

from io import BytesIO
from pathlib import Path

from PyPDF2 import PdfReader as PdfReader

from src.shared.utils.deepdoc.compat import find_codec


def get_text(file_name: str, binary: bytes | None = None) -> str:
    text = ""
    if binary is not None:
        encoding = find_codec(binary)
        return binary.decode(encoding, errors="ignore")

    with open(file_name, "r", encoding="utf-8", errors="ignore") as handle:
        while True:
            line = handle.readline()
            if not line:
                break
            text += line
    return text


def extract_pdf_outlines(source: str | bytes | Path):
    try:
        if isinstance(source, bytes):
            reader = PdfReader(BytesIO(source))
        else:
            reader = PdfReader(str(source))
        outlines = []

        def dfs(nodes, depth):
            for node in nodes:
                if isinstance(node, list):
                    dfs(node, depth + 1)
                else:
                    outlines.append((node["/Title"], depth, reader.get_destination_page_number(node) + 1))

        dfs(reader.outline, 0)
        return outlines
    except Exception:
        return []
