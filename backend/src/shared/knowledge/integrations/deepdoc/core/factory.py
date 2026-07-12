from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from novamind.shared.knowledge.integrations.deepdoc.core.capabilities import get_deepdoc_capabilities
from novamind.shared.knowledge.integrations.deepdoc.core.runtime_parser import DeepDocParser


@dataclass(frozen=True, slots=True)
class DeepDocParserSpec:
    parser_id: str
    file_type: str
    mode: str
    available: bool
    description: str


class DeepDocParserFactory:
    """RAGFlow-style parser selector for the vendored deepdoc module."""

    DEFAULT_PARSER_IDS: Dict[str, str] = {
        "pdf": "pdf_layout",
        "docx": "docx",
        "epub": "epub",
        "xls": "excel",
        "xlsx": "excel",
        "ppt": "ppt",
        "pptx": "ppt",
        "jpg": "figure",
        "jpeg": "figure",
        "png": "figure",
        "gif": "figure",
        "webp": "figure",
        "bmp": "figure",
        "txt": "txt",
        "md": "markdown",
        "markdown": "markdown",
        "csv": "text",
        "json": "json",
        "html": "html",
    }

    @classmethod
    def list_specs(cls) -> Dict[str, DeepDocParserSpec]:
        capabilities = get_deepdoc_capabilities()
        pdf_modes = capabilities["pdf_modes"]
        return {
            "pdf_plain": DeepDocParserSpec(
                parser_id="pdf_plain",
                file_type="pdf",
                mode="plain",
                available=bool(pdf_modes["plain"]["available"]),
                description=str(pdf_modes["plain"]["description"]),
            ),
            "pdf_layout": DeepDocParserSpec(
                parser_id="pdf_layout",
                file_type="pdf",
                mode="layout",
                available=bool(pdf_modes["layout"]["available"]),
                description=str(pdf_modes["layout"]["description"]),
            ),
            "pdf_vision": DeepDocParserSpec(
                parser_id="pdf_vision",
                file_type="pdf",
                mode="vision",
                available=bool(pdf_modes["vision"]["available"]),
                description=str(pdf_modes["vision"]["description"]),
            ),
            "pdf_docling": DeepDocParserSpec(
                parser_id="pdf_docling",
                file_type="pdf",
                mode="docling",
                available=bool(pdf_modes["docling"]["available"]),
                description=str(pdf_modes["docling"]["description"]),
            ),
            "pdf_mineru": DeepDocParserSpec(
                parser_id="pdf_mineru",
                file_type="pdf",
                mode="mineru",
                available=bool(pdf_modes["mineru"]["available"]),
                description=str(pdf_modes["mineru"]["description"]),
            ),
            "pdf_opendataloader": DeepDocParserSpec(
                parser_id="pdf_opendataloader",
                file_type="pdf",
                mode="opendataloader",
                available=bool(pdf_modes["opendataloader"]["available"]),
                description=str(pdf_modes["opendataloader"]["description"]),
            ),
            "pdf_paddleocr": DeepDocParserSpec(
                parser_id="pdf_paddleocr",
                file_type="pdf",
                mode="paddleocr",
                available=bool(pdf_modes["paddleocr"]["available"]),
                description=str(pdf_modes["paddleocr"]["description"]),
            ),
            "pdf_somark": DeepDocParserSpec(
                parser_id="pdf_somark",
                file_type="pdf",
                mode="somark",
                available=bool(pdf_modes["somark"]["available"]),
                description=str(pdf_modes["somark"]["description"]),
            ),
            "pdf_tcadp": DeepDocParserSpec(
                parser_id="pdf_tcadp",
                file_type="pdf",
                mode="tcadp",
                available=bool(pdf_modes["tcadp"]["available"]),
                description=str(pdf_modes["tcadp"]["description"]),
            ),
            "docx": DeepDocParserSpec(
                parser_id="docx",
                file_type="docx",
                mode="docx",
                available=True,
                description="Adapted from RAGFlow docx parser.",
            ),
            "epub": DeepDocParserSpec(
                parser_id="epub",
                file_type="epub",
                mode="epub",
                available=True,
                description="Adapted from RAGFlow epub parser.",
            ),
            "excel": DeepDocParserSpec(
                parser_id="excel",
                file_type="xlsx",
                mode="excel",
                available=True,
                description="Adapted from RAGFlow excel parser.",
            ),
            "ppt": DeepDocParserSpec(
                parser_id="ppt",
                file_type="pptx",
                mode="ppt",
                available=True,
                description="Adapted from RAGFlow ppt parser.",
            ),
            "figure": DeepDocParserSpec(
                parser_id="figure",
                file_type="png",
                mode="figure",
                available=True,
                description="Adapted image parser for jpg/jpeg/png/gif/webp/bmp files.",
            ),
            "text": DeepDocParserSpec(
                parser_id="text",
                file_type="text",
                mode="text",
                available=True,
                description="Text-family parser for txt/md/csv/json/html.",
            ),
            "txt": DeepDocParserSpec(
                parser_id="txt",
                file_type="txt",
                mode="txt",
                available=True,
                description="Adapted from RAGFlow txt parser.",
            ),
            "markdown": DeepDocParserSpec(
                parser_id="markdown",
                file_type="md",
                mode="markdown",
                available=True,
                description="Adapted from RAGFlow markdown parser.",
            ),
            "html": DeepDocParserSpec(
                parser_id="html",
                file_type="html",
                mode="html",
                available=True,
                description="Adapted from RAGFlow html parser.",
            ),
            "json": DeepDocParserSpec(
                parser_id="json",
                file_type="json",
                mode="json",
                available=True,
                description="Adapted from RAGFlow json parser.",
            ),
        }

    @classmethod
    def resolve_parser_id(cls, file_type: str, parser_id: str | None = None) -> DeepDocParserSpec:
        specs = cls.list_specs()
        normalized_file_type = file_type.lower().lstrip(".")
        resolved_id = parser_id or cls.DEFAULT_PARSER_IDS.get(normalized_file_type)
        if not resolved_id or resolved_id not in specs:
            raise ValueError(f"Unsupported deepdoc parser_id for file type '{file_type}': {parser_id}")
        return specs[resolved_id]

    @classmethod
    def build_configs(cls, file_type: str, parser_id: str | None = None) -> Tuple[DeepDocParser, dict]:
        spec = cls.resolve_parser_id(file_type, parser_id)
        parser = DeepDocParser()
        parsing_config = {}
        if spec.file_type == "pdf":
            if spec.mode in {"plain", "layout", "vision"}:
                parsing_config["deepdoc_pdf_mode"] = spec.mode
            parsing_config["deepdoc_parser_id"] = spec.parser_id
        elif spec.parser_id not in {"docx", "epub", "excel", "ppt", "figure", "text"}:
            parsing_config["deepdoc_parser_id"] = spec.parser_id
        return parser, parsing_config
