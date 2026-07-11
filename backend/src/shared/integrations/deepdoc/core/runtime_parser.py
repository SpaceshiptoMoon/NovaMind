from __future__ import annotations

import asyncio
from functools import cached_property
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from src.shared.integrations.deepdoc.core.capabilities import get_deepdoc_capabilities
from src.shared.integrations.deepdoc.logging_compat import get_logger
from src.shared.integrations.deepdoc.core.models import DeepDocParseResult
from src.shared.integrations.deepdoc.vision_runtime import ensure_vision_parser_available

logger = get_logger(__name__)


class DeepDocParser:
    """DeepDoc adapter using vendored RAGFlow pieces plus local compatibility shims."""

    @cached_property
    def _docx_parser(self):
        from src.shared.integrations.deepdoc.parsers.docx import RAGFlowDocxParser

        return RAGFlowDocxParser()

    @cached_property
    def _epub_parser(self):
        from src.shared.integrations.deepdoc.parsers.epub import RAGFlowEpubParser

        return RAGFlowEpubParser()

    @cached_property
    def _excel_parser(self):
        from src.shared.integrations.deepdoc.parsers.excel import RAGFlowExcelParser

        return RAGFlowExcelParser()

    @cached_property
    def _figure_parser(self):
        from src.shared.integrations.deepdoc.parsers.figure import RAGFlowFigureParser

        return RAGFlowFigureParser()

    @cached_property
    def _docling_parser(self):
        from src.shared.integrations.deepdoc.parsers.remote.docling import RAGFlowDoclingParser

        return RAGFlowDoclingParser()

    @cached_property
    def _mineru_parser(self):
        from src.shared.integrations.deepdoc.parsers.remote.mineru import RAGFlowMinerUParser

        return RAGFlowMinerUParser()

    @cached_property
    def _opendataloader_parser(self):
        from src.shared.integrations.deepdoc.parsers.remote.opendataloader import RAGFlowOpenDataLoaderParser

        return RAGFlowOpenDataLoaderParser()

    @cached_property
    def _paddleocr_parser(self):
        from src.shared.integrations.deepdoc.parsers.remote.paddleocr import RAGFlowPaddleOCRParser

        return RAGFlowPaddleOCRParser()

    @cached_property
    def _somark_parser(self):
        from src.shared.integrations.deepdoc.parsers.remote.somark import RAGFlowSoMarkParser

        return RAGFlowSoMarkParser()

    @cached_property
    def _tcadp_parser(self):
        from src.shared.integrations.deepdoc.parsers.remote.tcadp import RAGFlowTCADPParser

        return RAGFlowTCADPParser()

    @cached_property
    def _pdf_parser(self):
        from src.shared.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser

        return RAGFlowPdfParser()

    @cached_property
    def _ppt_parser(self):
        from src.shared.integrations.deepdoc.parsers.ppt import RAGFlowPptParser

        return RAGFlowPptParser()

    @cached_property
    def _text_parser(self):
        from src.shared.integrations.deepdoc.parsers.text import RAGFlowTextParser

        return RAGFlowTextParser()

    @staticmethod
    def supported_extensions() -> set[str]:
        return {"pdf", "docx", "epub", "txt", "md", "markdown", "csv", "json", "html", "xls", "xlsx", "ppt", "pptx", "jpg", "jpeg", "png", "gif", "webp", "bmp"}

    @staticmethod
    def supported_pdf_modes() -> Dict[str, Dict[str, Any]]:
        return dict(get_deepdoc_capabilities()["pdf_modes"])

    async def parse(
        self,
        file_path: Union[str, Path],
        *,
        parsing_config: Optional[Dict[str, Any]] = None,
        splitting_config: Optional[Dict[str, Any]] = None,
    ) -> DeepDocParseResult:
        file_path = Path(file_path)
        extension = file_path.suffix.lower().lstrip(".")
        parsing_config = parsing_config or {}
        splitting_config = splitting_config or {}
        return await self._parse_source(file_path, extension, parsing_config, splitting_config)

    async def parse_bytes(
        self,
        file_bytes: bytes,
        *,
        file_type: str,
        parsing_config: Optional[Dict[str, Any]] = None,
        splitting_config: Optional[Dict[str, Any]] = None,
    ) -> DeepDocParseResult:
        extension = file_type.lower().lstrip(".")
        parsing_config = parsing_config or {}
        splitting_config = splitting_config or {}
        return await self._parse_source(file_bytes, extension, parsing_config, splitting_config)

    async def _parse_source(
        self,
        source: Union[Path, bytes],
        extension: str,
        parsing_config: Dict[str, Any],
        splitting_config: Dict[str, Any],
    ) -> DeepDocParseResult:
        if extension == "pdf":
            return await asyncio.to_thread(self._parse_pdf_sync, source, parsing_config, splitting_config)
        if extension == "docx":
            return await asyncio.to_thread(self._parse_docx_sync, source, splitting_config)
        if extension == "epub":
            return await asyncio.to_thread(self._parse_epub_sync, source, splitting_config)
        if extension in {"xls", "xlsx"}:
            return await asyncio.to_thread(self._parse_excel_sync, source, extension, splitting_config)
        if extension in {"ppt", "pptx"}:
            return await asyncio.to_thread(self._parse_ppt_sync, source, extension, splitting_config)
        if extension in {"jpg", "jpeg", "png", "gif", "webp", "bmp"}:
            return await asyncio.to_thread(self._parse_figure_sync, source, extension, splitting_config)
        if extension in {"txt", "md", "markdown", "csv", "json", "html"}:
            return await asyncio.to_thread(self._parse_text_sync, source, extension, parsing_config, splitting_config)
        raise ValueError(f"DeepDoc does not support file type: {extension}")

    def _parse_pdf_sync(
        self,
        source: Union[Path, bytes],
        parsing_config: Dict[str, Any],
        splitting_config: Dict[str, Any],
    ) -> DeepDocParseResult:
        parser_id = str(parsing_config.get("deepdoc_parser_id", "") or "")
        if parser_id == "pdf_docling":
            if isinstance(source, Path):
                full_text, default_chunks, metadata = self._docling_parser.parse(source)
            else:
                full_text, default_chunks, metadata = self._docling_parser.parse_bytes(source)
            chunks = self._chunk_blocks(default_chunks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
            return DeepDocParseResult(full_text=full_text, chunks=chunks, metadata=metadata)
        if parser_id == "pdf_opendataloader":
            if isinstance(source, Path):
                full_text, default_chunks, metadata = self._opendataloader_parser.parse(source)
            else:
                full_text, default_chunks, metadata = self._opendataloader_parser.parse_bytes(source)
            chunks = self._chunk_blocks(default_chunks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
            return DeepDocParseResult(full_text=full_text, chunks=chunks, metadata=metadata)
        if parser_id == "pdf_mineru":
            if isinstance(source, Path):
                full_text, default_chunks, metadata = self._mineru_parser.parse(source)
            else:
                full_text, default_chunks, metadata = self._mineru_parser.parse_bytes(source, parsing_config=parsing_config)
            chunks = self._chunk_blocks(default_chunks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
            return DeepDocParseResult(full_text=full_text, chunks=chunks, metadata=metadata)
        if parser_id == "pdf_paddleocr":
            if isinstance(source, Path):
                full_text, default_chunks, metadata = self._paddleocr_parser.parse(source)
            else:
                full_text, default_chunks, metadata = self._paddleocr_parser.parse_bytes(source)
            chunks = self._chunk_blocks(default_chunks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
            return DeepDocParseResult(full_text=full_text, chunks=chunks, metadata=metadata)
        if parser_id == "pdf_somark":
            if isinstance(source, Path):
                full_text, default_chunks, metadata = self._somark_parser.parse(source)
            else:
                full_text, default_chunks, metadata = self._somark_parser.parse_bytes(source, parsing_config=parsing_config)
            chunks = self._chunk_blocks(default_chunks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
            return DeepDocParseResult(full_text=full_text, chunks=chunks, metadata=metadata)
        if parser_id == "pdf_tcadp":
            if isinstance(source, Path):
                full_text, default_chunks, metadata = self._tcadp_parser.parse(source)
            else:
                full_text, default_chunks, metadata = self._tcadp_parser.parse_bytes(source, parsing_config=parsing_config)
            chunks = self._chunk_blocks(default_chunks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
            return DeepDocParseResult(full_text=full_text, chunks=chunks, metadata=metadata)

        pdf_mode = str(parsing_config.get("deepdoc_pdf_mode", "layout"))
        pdf_modes = self.supported_pdf_modes()
        if pdf_mode not in pdf_modes:
            raise ValueError(f"Unsupported DeepDoc PDF mode: {pdf_mode}")
        if not pdf_modes[pdf_mode]["available"]:
            if pdf_mode == "vision":
                ensure_vision_parser_available()
            missing = ", ".join(pdf_modes[pdf_mode].get("missing", []))
            raise RuntimeError(f"DeepDoc PDF mode '{pdf_mode}' is not available: {missing}")
        pdf_input = str(source) if isinstance(source, Path) else source
        return self._pdf_parser(pdf_input, pdf_mode=pdf_mode, chunk_size=int(splitting_config.get("chunk_size", 1000)))

    def _parse_text_sync(
        self,
        source: Union[Path, bytes],
        extension: str,
        parsing_config: Dict[str, Any],
        splitting_config: Dict[str, Any],
    ) -> DeepDocParseResult:
        if isinstance(source, Path):
            full_text, default_chunks, parser_metadata = self._text_parser.parse(source, parser_id=parsing_config.get("deepdoc_parser_id"))
            file_type = source.suffix.lower().lstrip(".")
        else:
            full_text, default_chunks, parser_metadata = self._text_parser.parse_bytes(source, extension, parser_id=parsing_config.get("deepdoc_parser_id"))
            file_type = extension
        chunks = self._chunk_blocks(default_chunks or [full_text], chunk_size=int(splitting_config.get("chunk_size", 1000)))
        return DeepDocParseResult(
            full_text=full_text.strip(),
            chunks=chunks,
            metadata={"parser": "deepdoc", "file_type": file_type, "source": "ragflow-adapted", **parser_metadata},
        )

    def _parse_docx_sync(self, source: Union[Path, bytes], splitting_config: Dict[str, Any]) -> DeepDocParseResult:
        parser_input = str(source) if isinstance(source, Path) else source
        sections, tables = self._docx_parser(parser_input)
        blocks: List[str] = []
        heading_stack: List[str] = []
        image_count = 0

        for section in sections:
            text = (section.get("text") or "").strip()
            style_name = section.get("style") or ""
            image = section.get("image")
            if image:
                image_count += 1
            if not text:
                continue
            if style_name.startswith("Heading"):
                level = self._extract_heading_level(style_name)
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(text)
                blocks.append(f"# {' > '.join(heading_stack)}")
            else:
                blocks.append(text)

        flattened_tables: List[str] = []
        for group in tables:
            for item in group:
                item = item.strip()
                if item:
                    flattened_tables.append(item)
                    blocks.append(self._table_text_to_html(item))

        full_text = "\n\n".join(blocks).strip()
        chunks = self._chunk_blocks(blocks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
        return DeepDocParseResult(
            full_text=full_text,
            chunks=chunks,
            metadata={
                "parser": "deepdoc",
                "file_type": "docx",
                "sections": sections,
                "tables": flattened_tables,
                "images": image_count,
                "source": "ragflow-adapted",
            },
        )

    def _parse_excel_sync(
        self,
        source: Union[Path, bytes],
        extension: str,
        splitting_config: Dict[str, Any],
    ) -> DeepDocParseResult:
        parser_input = str(source) if isinstance(source, Path) else source
        blocks = self._excel_parser.html(parser_input) or self._excel_parser(parser_input)
        full_text = "\n\n".join(block.strip() for block in blocks if block and block.strip()).strip()
        chunks = self._chunk_blocks(blocks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
        return DeepDocParseResult(
            full_text=full_text,
            chunks=chunks,
            metadata={
                "parser": "deepdoc",
                "file_type": extension,
                "parser_class": "RAGFlowExcelParser",
                "source": "ragflow-adapted",
                "table_chunks": len(blocks),
            },
        )

    def _parse_epub_sync(self, source: Union[Path, bytes], splitting_config: Dict[str, Any]) -> DeepDocParseResult:
        if isinstance(source, Path):
            sections = self._epub_parser(str(source))
        else:
            sections = self._epub_parser("memory.epub", binary=source)
        full_text = "\n\n".join(section.strip() for section in sections if section and section.strip()).strip()
        chunks = self._chunk_blocks(sections, chunk_size=int(splitting_config.get("chunk_size", 1000)))
        return DeepDocParseResult(
            full_text=full_text,
            chunks=chunks,
            metadata={
                "parser": "deepdoc",
                "file_type": "epub",
                "parser_class": "RAGFlowEpubParser",
                "source": "ragflow-adapted",
                "sections": len(sections),
            },
        )

    def _parse_ppt_sync(
        self,
        source: Union[Path, bytes],
        extension: str,
        splitting_config: Dict[str, Any],
    ) -> DeepDocParseResult:
        parser_input = str(source) if isinstance(source, Path) else source
        slides = self._ppt_parser(parser_input)
        blocks = [f"# Slide {index + 1}\n{slide}".strip() for index, slide in enumerate(slides) if slide and slide.strip()]
        full_text = "\n\n".join(blocks).strip()
        chunks = self._chunk_blocks(blocks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
        return DeepDocParseResult(
            full_text=full_text,
            chunks=chunks,
            metadata={
                "parser": "deepdoc",
                "file_type": extension,
                "parser_class": "RAGFlowPptParser",
                "source": "ragflow-adapted",
                "slides": len(slides),
            },
        )

    def _parse_figure_sync(
        self,
        source: Union[Path, bytes],
        extension: str,
        splitting_config: Dict[str, Any],
    ) -> DeepDocParseResult:
        if isinstance(source, Path):
            full_text, default_chunks, metadata = self._figure_parser.parse(source)
        else:
            full_text, default_chunks, metadata = self._figure_parser.parse_bytes(source, extension)
        chunks = self._chunk_blocks(default_chunks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
        return DeepDocParseResult(full_text=full_text, chunks=chunks, metadata=metadata)

    @staticmethod
    def _extract_heading_level(style_name: str) -> int:
        suffix = style_name.replace("Heading", "").strip()
        try:
            return max(1, int(suffix))
        except ValueError:
            return 1

    @staticmethod
    def _table_text_to_html(table_text: str) -> str:
        rows = [row.strip() for row in table_text.split("\n") if row.strip()]
        if not rows:
            return ""
        html_rows = []
        for row in rows:
            cells = [cell.strip() for cell in row.split(";") if cell.strip()]
            html_rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
        return "<table>" + "".join(html_rows) + "</table>"

    @staticmethod
    def _chunk_blocks(blocks: Sequence[str], chunk_size: int) -> List[str]:
        chunks: List[str] = []
        current_parts: List[str] = []
        current_length = 0
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            addition = len(block) + (2 if current_parts else 0)
            if current_parts and current_length + addition > chunk_size:
                chunks.append("\n\n".join(current_parts))
                current_parts = [block]
                current_length = len(block)
                continue
            current_parts.append(block)
            current_length += addition
        if current_parts:
            chunks.append("\n\n".join(current_parts))
        return chunks
