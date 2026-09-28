"""DeepDoc 运行时解析器：应用层封装，组合 engine + factory + 后处理。"""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from functools import cached_property
from pathlib import Path
from typing import Any

from novamind.engines.document.integrations.deepdoc.core.capabilities import (
    get_deepdoc_capabilities,
)
from novamind.engines.document.integrations.deepdoc.core.models import DeepDocParseResult
from novamind.engines.document.integrations.deepdoc.vision_runtime import (
    ensure_vision_parser_available,
)
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class DeepDocParser:
    """DeepDoc adapter using vendored RAGFlow pieces plus local compatibility shims."""

    @cached_property
    def _docx_parser(self):
        """DOCX 解析器（懒加载防 import 重）。"""
        from novamind.engines.document.integrations.deepdoc.parsers.docx import RAGFlowDocxParser

        return RAGFlowDocxParser()

    @cached_property
    def _epub_parser(self):
        """EPUB 解析器（懒加载）。"""
        from novamind.engines.document.integrations.deepdoc.parsers.epub import RAGFlowEpubParser

        return RAGFlowEpubParser()

    @cached_property
    def _excel_parser(self):
        """Excel 解析器（懒加载）。"""
        from novamind.engines.document.integrations.deepdoc.parsers.excel import RAGFlowExcelParser

        return RAGFlowExcelParser()

    @cached_property
    def _figure_parser(self):
        """图片解析器（懒加载）。"""
        from novamind.engines.document.integrations.deepdoc.parsers.figure import (
            RAGFlowFigureParser,
        )

        return RAGFlowFigureParser()

    @cached_property
    def _pdf_parser(self):
        """PDF 解析器（懒加载，含 OCR/layout 全依赖）。"""
        from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser

        return RAGFlowPdfParser()

    @cached_property
    def _ppt_parser(self):
        """PPT 解析器（懒加载）。"""
        from novamind.engines.document.integrations.deepdoc.parsers.ppt import RAGFlowPptParser

        return RAGFlowPptParser()

    @cached_property
    def _text_parser(self):
        """文本族解析器（txt/md/html/json 路由，懒加载）。"""
        from novamind.engines.document.integrations.deepdoc.parsers.text import RAGFlowTextParser

        return RAGFlowTextParser()

    @staticmethod
    def supported_extensions() -> set[str]:
        """支持的文件后缀全集（含图片与文本族）。"""
        return {"pdf", "docx", "epub", "txt", "md", "markdown", "csv", "json", "html", "xls", "xlsx", "ppt", "pptx", "jpg", "jpeg", "png", "gif", "webp", "bmp"}

    @staticmethod
    def supported_pdf_modes() -> dict[str, dict[str, Any]]:
        """PDF 解析模式能力表（full/plain 及其 available/missing）。"""
        return dict(get_deepdoc_capabilities()["pdf_modes"])

    async def parse(
        self,
        file_path: str | Path,
        *,
        parsing_config: dict[str, Any] | None = None,
        splitting_config: dict[str, Any] | None = None,
    ) -> DeepDocParseResult:
        """解析本地文件为 DeepDocParseResult（CPU 重活在 to_thread）。
        
        Args:
            file_path: 文件路径。
            parsing_config: 解析配置（deepdoc_parser_id/deepdoc_pdf_mode 等）。
            splitting_config: 分块配置（chunk_size）。
        
        Raises:
            ValueError: 文件类型不支持。
        """
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
        parsing_config: dict[str, Any] | None = None,
        splitting_config: dict[str, Any] | None = None,
    ) -> DeepDocParseResult:
        """解析字节流为 DeepDocParseResult（file_type 显式指定后缀）。

        Args:
            file_bytes: 文件字节流。
            file_type: 文件后缀（决定路由的解析器）。
            parsing_config: 解析配置（deepdoc_parser_id / deepdoc_pdf_mode 等），可空。
            splitting_config: 切分配置（chunk_size 等），可空。

        Returns:
            DeepDocParseResult。

        Raises:
            ValueError: 文件类型不支持。
        """
        extension = file_type.lower().lstrip(".")
        parsing_config = parsing_config or {}
        splitting_config = splitting_config or {}
        return await self._parse_source(file_bytes, extension, parsing_config, splitting_config)

    async def _parse_source(
        self,
        source: Path | bytes,
        extension: str,
        parsing_config: dict[str, Any],
        splitting_config: dict[str, Any],
    ) -> DeepDocParseResult:
        """按后缀路由到对应同步解析方法（各包 to_thread 防事件循环阻塞）。"""
        logger.info(
            "DeepDoc 解析路由",
            extension=extension,
            deepdoc_parser_id=parsing_config.get("deepdoc_parser_id"),
            deepdoc_pdf_mode=parsing_config.get("deepdoc_pdf_mode"),
            source_type="file" if isinstance(source, Path) else "bytes",
        )
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
        source: Path | bytes,
        parsing_config: dict[str, Any],
        splitting_config: dict[str, Any],
    ) -> DeepDocParseResult:
        """PDF 同步解析：校验模式可用性 → 调 RAGFlowPdfParser。
        
        Raises:
            ValueError: pdf_mode 不在能力表。
            RuntimeError: 模式不可用（模型/依赖缺失）。
        """
        parser_id = str(parsing_config.get("deepdoc_parser_id", "") or "")
        logger.info(
            "DeepDoc PDF 解析开始",
            parser_id=parser_id or "(auto)",
            deepdoc_pdf_mode=parsing_config.get("deepdoc_pdf_mode", "full"),
            chunk_size=splitting_config.get("chunk_size", 1000),
            source_type="file" if isinstance(source, Path) else "bytes",
        )
        pdf_mode = str(parsing_config.get("deepdoc_pdf_mode", "full"))
        pdf_modes = self.supported_pdf_modes()
        if pdf_mode not in pdf_modes:
            raise ValueError(f"Unsupported DeepDoc PDF mode: {pdf_mode}")
        if not pdf_modes[pdf_mode]["available"]:
            if pdf_mode == "full":
                ensure_vision_parser_available()
            missing = ", ".join(pdf_modes[pdf_mode].get("missing", []))
            raise RuntimeError(f"DeepDoc PDF mode '{pdf_mode}' is not available: {missing}")
        logger.info(
            "DeepDoc PDF 使用本地解析器",
            pdf_mode=pdf_mode,
            parser_id=parser_id or "(full/default)",
        )
        pdf_input = str(source) if isinstance(source, Path) else source
        # 公式识别（pix2text-mfr）：None = 默认开启（模型在时识别 equation 区域），
        # 显式 False 关闭。模型缺失时解析器内部 WARNING 软降级，不影响可用性。
        formula_recognition = parsing_config.get("deepdoc_formula_recognition")
        result = self._pdf_parser(
            pdf_input,
            pdf_mode=pdf_mode,
            chunk_size=int(splitting_config.get("chunk_size", 1000)),
            formula_recognition=None if formula_recognition is None else bool(formula_recognition),
        )
        logger.info(
            "DeepDoc PDF 解析完成",
            pdf_mode=pdf_mode,
            char_count=len(result.full_text),
            chunk_count=len(result.chunks),
        )
        return result

    def _parse_text_sync(
        self,
        source: Path | bytes,
        extension: str,
        parsing_config: dict[str, Any],
        splitting_config: dict[str, Any],
    ) -> DeepDocParseResult:
        """文本族同步解析：路由到 txt/md/html/json 子解析器再统一聚块。"""
        logger.info("DeepDoc 文本解析开始", extension=extension, deepdoc_parser_id=parsing_config.get("deepdoc_parser_id"))
        if isinstance(source, Path):
            full_text, default_chunks, parser_metadata = self._text_parser.parse(source, parser_id=parsing_config.get("deepdoc_parser_id"))
            file_type = source.suffix.lower().lstrip(".")
        else:
            full_text, default_chunks, parser_metadata = self._text_parser.parse_bytes(source, extension, parser_id=parsing_config.get("deepdoc_parser_id"))
            file_type = extension
        chunks = self._chunk_blocks(default_chunks or [full_text], chunk_size=int(splitting_config.get("chunk_size", 1000)))
        logger.info("DeepDoc 文本解析完成", extension=extension, char_count=len(full_text), chunk_count=len(chunks))
        return DeepDocParseResult(
            full_text=full_text.strip(),
            chunks=chunks,
            metadata={"parser": "deepdoc", "file_type": file_type, "source": "ragflow-adapted", **parser_metadata},
        )

    def _parse_docx_sync(self, source: Path | bytes, splitting_config: dict[str, Any]) -> DeepDocParseResult:
        """DOCX 同步解析：Heading 样式转 Markdown 层级标题，表格转 HTML。"""
        logger.info("DeepDoc DOCX 解析开始")
        parser_input = str(source) if isinstance(source, Path) else source
        sections, tables = self._docx_parser(parser_input)
        blocks: list[str] = []
        heading_stack: list[str] = []
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

        flattened_tables: list[str] = []
        for group in tables:
            for item in group:
                item = item.strip()
                if item:
                    flattened_tables.append(item)
                    blocks.append(self._table_text_to_html(item))

        full_text = "\n\n".join(blocks).strip()
        chunks = self._chunk_blocks(blocks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
        logger.info("DeepDoc DOCX 解析完成", char_count=len(full_text), chunk_count=len(chunks), sections=len(sections), images=image_count)
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
        source: Path | bytes,
        extension: str,
        splitting_config: dict[str, Any],
    ) -> DeepDocParseResult:
        """Excel 同步解析：优先 HTML 表格块，空结果回退行文本。"""
        logger.info("DeepDoc Excel 解析开始", extension=extension)
        parser_input = str(source) if isinstance(source, Path) else source
        blocks = self._excel_parser.html(parser_input) or self._excel_parser(parser_input)
        full_text = "\n\n".join(block.strip() for block in blocks if block and block.strip()).strip()
        chunks = self._chunk_blocks(blocks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
        logger.info("DeepDoc Excel 解析完成", extension=extension, char_count=len(full_text), chunk_count=len(chunks), table_chunks=len(blocks))
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

    def _parse_epub_sync(self, source: Path | bytes, splitting_config: dict[str, Any]) -> DeepDocParseResult:
        """EPUB 同步解析：按 spine 序章节切分聚块。"""
        logger.info("DeepDoc EPUB 解析开始")
        if isinstance(source, Path):
            sections = self._epub_parser(str(source))
        else:
            sections = self._epub_parser("memory.epub", binary=source)
        full_text = "\n\n".join(section.strip() for section in sections if section and section.strip()).strip()
        chunks = self._chunk_blocks(sections, chunk_size=int(splitting_config.get("chunk_size", 1000)))
        logger.info("DeepDoc EPUB 解析完成", char_count=len(full_text), chunk_count=len(chunks), sections=len(sections))
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
        source: Path | bytes,
        extension: str,
        splitting_config: dict[str, Any],
    ) -> DeepDocParseResult:
        """PPT 同步解析：每页加 Slide 标题行后聚块。"""
        logger.info("DeepDoc PPT 解析开始", extension=extension)
        parser_input = str(source) if isinstance(source, Path) else source
        slides = self._ppt_parser(parser_input)
        blocks = [f"# Slide {index + 1}\n{slide}".strip() for index, slide in enumerate(slides) if slide and slide.strip()]
        full_text = "\n\n".join(blocks).strip()
        chunks = self._chunk_blocks(blocks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
        logger.info("DeepDoc PPT 解析完成", extension=extension, char_count=len(full_text), chunk_count=len(chunks), slides=len(slides))
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
        source: Path | bytes,
        extension: str,
        splitting_config: dict[str, Any],
    ) -> DeepDocParseResult:
        """图片同步解析：OCR 文本行 + 元数据直通。"""
        logger.info("DeepDoc 图片解析开始", extension=extension)
        if isinstance(source, Path):
            full_text, default_chunks, metadata = self._figure_parser.parse(source)
        else:
            full_text, default_chunks, metadata = self._figure_parser.parse_bytes(source, extension)
        chunks = self._chunk_blocks(default_chunks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
        logger.info("DeepDoc 图片解析完成", extension=extension, char_count=len(full_text), chunk_count=len(chunks))
        return DeepDocParseResult(full_text=full_text, chunks=chunks, metadata=metadata)

    @staticmethod
    def _extract_heading_level(style_name: str) -> int:
        """从 Heading N 样式名取级别（非法回退 1）。"""
        suffix = style_name.replace("Heading", "").strip()
        try:
            return max(1, int(suffix))
        except ValueError:
            return 1

    @staticmethod
    def _table_text_to_html(table_text: str) -> str:
        """「a: b; c: d」行文本转简单 HTML 表格。"""
        rows = [row.strip() for row in table_text.split("\n") if row.strip()]
        if not rows:
            return ""
        html_rows = []
        for row in rows:
            cells = [cell.strip() for cell in row.split(";") if cell.strip()]
            html_rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
        return "<table>" + "".join(html_rows) + "</table>"

    @staticmethod
    def _chunk_blocks(blocks: Sequence[str], chunk_size: int) -> list[str]:
        """字符长度聚块：块间空行拼接，超 chunk_size 先出当前块。"""
        chunks: list[str] = []
        current_parts: list[str] = []
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
