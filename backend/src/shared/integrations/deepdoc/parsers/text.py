from __future__ import annotations

# Unified text-family router backed by RAGFlow parser adaptations.

from pathlib import Path

from src.shared.integrations.deepdoc.parsers.html import RAGFlowHtmlParser
from src.shared.integrations.deepdoc.parsers.json import RAGFlowJsonParser
from src.shared.integrations.deepdoc.parsers.markdown import (
    MarkdownElementExtractor,
    RAGFlowMarkdownParser,
)
from src.shared.integrations.deepdoc.parsers.txt import RAGFlowTxtParser
from src.shared.integrations.deepdoc.parsers.upstream.utils import get_text


class RAGFlowTextParser:
    def __init__(self):
        self._txt_parser = RAGFlowTxtParser()
        self._markdown_parser = RAGFlowMarkdownParser()
        self._html_parser = RAGFlowHtmlParser()
        self._json_parser = RAGFlowJsonParser()

    def parse(self, file_path: str | Path, parser_id: str | None = None) -> tuple[str, list[str], dict]:
        path = Path(file_path)
        suffix = path.suffix.lower().lstrip(".")
        return self.parse_bytes(path.read_bytes(), suffix, parser_id=parser_id)

    def parse_bytes(self, file_bytes: bytes, file_type: str, parser_id: str | None = None) -> tuple[str, list[str], dict]:
        suffix = file_type.lower().lstrip(".")
        parser_id = (parser_id or "").lower()

        if suffix in {"txt", "csv"} or parser_id == "txt":
            sections = self._txt_parser("", binary=file_bytes)
            text = get_text("", binary=file_bytes)
            chunks = [section[0] for section in sections if section and section[0].strip()]
            return text, chunks or ([text] if text.strip() else []), {"parser_class": "RAGFlowTxtParser"}

        if suffix in {"md", "markdown"} or parser_id == "markdown":
            text = get_text("", binary=file_bytes)
            text_without_tables, tables = self._markdown_parser.extract_tables_and_remainder(text, separate_tables=False)
            sections = MarkdownElementExtractor(text_without_tables).extract_elements()
            chunks = [section for section in sections if section.strip()]
            chunks.extend(table for table in tables if table.strip())
            return text, chunks or ([text] if text.strip() else []), {"parser_class": "RAGFlowMarkdownParser"}

        if suffix == "html" or parser_id == "html":
            sections = self._html_parser("", binary=file_bytes)
            text = "\n\n".join(section for section in sections if section.strip()).strip()
            return text, sections, {"parser_class": "RAGFlowHtmlParser"}

        if suffix == "json" or parser_id == "json":
            sections = self._json_parser(file_bytes)
            text = get_text("", binary=file_bytes)
            return text, sections or ([text] if text.strip() else []), {"parser_class": "RAGFlowJsonParser"}

        raise ValueError(f"Unsupported text format for deepdoc text parser: {suffix}")
