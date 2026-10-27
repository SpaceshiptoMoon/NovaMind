"""DeepDoc 运行时解析器：应用层封装，组合 engine + factory + 后处理。"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from functools import cached_property
from pathlib import Path
from typing import Any

from novamind.engines.document.integrations.deepdoc.core.capabilities import (
    get_deepdoc_capabilities,
)
from novamind.engines.document.integrations.deepdoc.core.models import DeepDocParseResult
from novamind.engines.document.integrations.deepdoc.core.quality import (
    build_quality_metadata,
    collect_warnings,
)
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
            return await asyncio.to_thread(self._parse_excel_sync, source, extension, parsing_config, splitting_config)
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
        # 发包模式：模型不可用类失败（版面识别/公式识别）策略由宿主经
        # parsing_config 声明（默认回退保持既有行为；"raise" 时抛
        # LayoutInferenceError / FormulaModelUnavailableError 由宿主决策）
        model_failure_policy = parsing_config.get(
            "deepdoc_model_failure_policy", "heuristic_fallback"
        )
        started = time.perf_counter()
        with collect_warnings() as warnings:
            result = self._pdf_parser(
                pdf_input,
                pdf_mode=pdf_mode,
                chunk_size=int(splitting_config.get("chunk_size", 1000)),
                formula_recognition=None if formula_recognition is None else bool(formula_recognition),
                model_failure_policy=str(model_failure_policy),
            )
        result.metadata["quality"] = build_quality_metadata(
            "deepdoc", warnings, started, pdf_mode=pdf_mode
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
        started = time.perf_counter()
        with collect_warnings() as warnings:
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
            metadata={
                "parser": "deepdoc",
                "file_type": file_type,
                "source": "ragflow-adapted",
                "quality": build_quality_metadata("deepdoc", warnings, started),
                **parser_metadata,
            },
        )

    def _parse_docx_sync(self, source: Path | bytes, splitting_config: dict[str, Any]) -> DeepDocParseResult:
        """DOCX 同步解析：Heading 样式转 Markdown 层级标题，表格转 HTML。"""
        logger.info("DeepDoc DOCX 解析开始")
        parser_input = str(source) if isinstance(source, Path) else source
        started = time.perf_counter()
        with collect_warnings() as warnings:
            sections, tables = self._docx_parser(parser_input)
        blocks: list[str] = []
        heading_stack: list[str] = []
        image_count = 0
        flattened_tables: list[str] = []

        for section in sections:
            image = section.get("image")
            if image:
                image_count += 1
            # 表格占位项：把对应表格文本插回文档原位（body 序），不再堆尾
            table_index = section.get("table_index")
            if table_index is not None and 0 <= table_index < len(tables):
                for item in tables[table_index]:
                    item = item.strip()
                    if item:
                        flattened_tables.append(item)
                        blocks.append(self._table_text_to_html(item))
                continue
            text = (section.get("text") or "").strip()
            style_name = section.get("style") or ""
            if not text:
                continue
            if style_name.startswith("Heading"):
                level = self._extract_heading_level(style_name)
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(text)
                # # 数量反映层级（H1→#，H2→##…封顶 6），路径保留检索语境
                prefix = "#" * min(level, 6)
                blocks.append(f"{prefix} {' > '.join(heading_stack)}")
            else:
                blocks.append(text)

        # 兜底：body 序之外残留的表格（异常文档结构）按旧约定追加尾部
        seen_table_indexes = {
            s.get("table_index") for s in sections if s.get("table_index") is not None
        }
        for group_index, group in enumerate(tables):
            if group_index in seen_table_indexes:
                continue
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
                "quality": build_quality_metadata("deepdoc", warnings, started),
            },
        )

    def _parse_excel_sync(
        self,
        source: Path | bytes,
        extension: str,
        parsing_config: dict[str, Any],
        splitting_config: dict[str, Any],
    ) -> DeepDocParseResult:
        """Excel 同步解析：HTML 表格块（多级表头折成复合表头）+ 嵌入图片提取。

        图片经 figure_regions 契约交宿主 figure 管线（上传 MinIO + 占位符
        换短路径，与 PDF figure 同链）；行文本兜底路径无占位符，图片仍上传
        可经 figure 代理访问。parsing_config 的 excel_max_loaded_mb（宿主
        资源旋钮，0 不限）透传给解析器：超限时切换 read_only 流式解析，
        合并展开/批注/图片/图表/公式回填降级为不可用。
        """
        max_loaded_mb = int(parsing_config.get("excel_max_loaded_mb") or 0)
        logger.info(
            "DeepDoc Excel 解析开始", extension=extension, max_loaded_mb=max_loaded_mb
        )
        parser_input = str(source) if isinstance(source, Path) else source
        started = time.perf_counter()
        with collect_warnings() as warnings:
            blocks, embedded_images = self._excel_parser.parse_blocks(
                parser_input, max_loaded_mb=max_loaded_mb
            )
            if not blocks:
                blocks = list(self._excel_parser(parser_input, max_loaded_mb=max_loaded_mb))
        figure_regions = self._build_excel_figure_regions(embedded_images)
        full_text = "\n\n".join(block.strip() for block in blocks if block and block.strip()).strip()
        chunks = self._chunk_blocks(blocks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
        logger.info(
            "DeepDoc Excel 解析完成",
            extension=extension,
            char_count=len(full_text),
            chunk_count=len(chunks),
            table_chunks=len(blocks),
            embedded_images=len(figure_regions),
        )
        return DeepDocParseResult(
            full_text=full_text,
            chunks=chunks,
            metadata={
                "parser": "deepdoc",
                "file_type": extension,
                "parser_class": "RAGFlowExcelParser",
                "source": "ragflow-adapted",
                "table_chunks": len(blocks),
                "figure_regions": figure_regions,
                "quality": build_quality_metadata("deepdoc", warnings, started),
            },
        )

    @staticmethod
    def _build_excel_figure_regions(embedded_images: list[dict]) -> list[dict[str, Any]]:
        """把 Excel 嵌入图片组装为 figure_regions 契约（复用 PDF figure 管线）。

        artifact_id 由解析器（parse_blocks）定版——正文占位符与 region 必须
        同一 id，此处复用不重生成。
        """
        figure_regions: list[dict[str, Any]] = []
        for image in embedded_images:
            blob = image.get("blob")
            artifact_id = str(image.get("artifact_id") or "")
            if not blob or not artifact_id:
                continue
            sheet = str(image.get("sheet") or "sheet")
            row = image.get("row")
            location = (
                f"r{int(row) + 1}"
                if row is not None
                else "未知位置"
            )
            figure_regions.append({
                "artifact_id": artifact_id,
                "pages": [],
                "page_start": 0,
                "bbox": {},
                "caption": f"{sheet} 工作表嵌入图片（{location}）",
                "text": "",
                "member_texts": [],
                "member_bboxes": [],
                "has_image": True,
                "image_blobs": [blob],
            })
        return figure_regions

    def _parse_epub_sync(self, source: Path | bytes, splitting_config: dict[str, Any]) -> DeepDocParseResult:
        """EPUB 同步解析：按 spine 序章节切分聚块。"""
        logger.info("DeepDoc EPUB 解析开始")
        started = time.perf_counter()
        with collect_warnings() as warnings:
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
                "quality": build_quality_metadata("deepdoc", warnings, started),
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
        started = time.perf_counter()
        with collect_warnings() as warnings:
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
                "quality": build_quality_metadata("deepdoc", warnings, started),
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
        started = time.perf_counter()
        with collect_warnings() as warnings:
            if isinstance(source, Path):
                full_text, default_chunks, metadata = self._figure_parser.parse(source)
            else:
                full_text, default_chunks, metadata = self._figure_parser.parse_bytes(source, extension)
        chunks = self._chunk_blocks(default_chunks, chunk_size=int(splitting_config.get("chunk_size", 1000)))
        logger.info("DeepDoc 图片解析完成", extension=extension, char_count=len(full_text), chunk_count=len(chunks))
        metadata["quality"] = build_quality_metadata("deepdoc", warnings, started)
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
