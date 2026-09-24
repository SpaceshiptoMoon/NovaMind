"""DeepDoc 解析器工厂：按文件类型 / 能力矩阵创建对应解析器实例。"""
from __future__ import annotations

from dataclasses import dataclass

from novamind.engines.document.integrations.deepdoc.core.capabilities import (
    get_deepdoc_capabilities,
)
from novamind.engines.document.integrations.deepdoc.core.runtime_parser import DeepDocParser


@dataclass(frozen=True, slots=True)
class DeepDocParserSpec:
    parser_id: str
    file_type: str
    mode: str
    available: bool


class DeepDocParserFactory:
    """RAGFlow-style parser selector for the vendored deepdoc module."""

    DEFAULT_PARSER_IDS: dict[str, str] = {
        "pdf": "pdf_full",
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
    def list_specs(cls) -> dict[str, DeepDocParserSpec]:
        capabilities = get_deepdoc_capabilities()
        pdf_modes = capabilities["pdf_modes"]
        return {
            "pdf_plain": DeepDocParserSpec(
                parser_id="pdf_plain",
                file_type="pdf",
                mode="plain",
                available=bool(pdf_modes["plain"]["available"]),
            ),
            "pdf_full": DeepDocParserSpec(
                parser_id="pdf_full",
                file_type="pdf",
                mode="full",
                available=bool(pdf_modes["full"]["available"]),
            ),
            "docx": DeepDocParserSpec(
                parser_id="docx",
                file_type="docx",
                mode="docx",
                available=True,
            ),
            "epub": DeepDocParserSpec(
                parser_id="epub",
                file_type="epub",
                mode="epub",
                available=True,
            ),
            "excel": DeepDocParserSpec(
                parser_id="excel",
                file_type="xlsx",
                mode="excel",
                available=True,
            ),
            "ppt": DeepDocParserSpec(
                parser_id="ppt",
                file_type="pptx",
                mode="ppt",
                available=True,
            ),
            "figure": DeepDocParserSpec(
                parser_id="figure",
                file_type="png",
                mode="figure",
                available=True,
            ),
            "text": DeepDocParserSpec(
                parser_id="text",
                file_type="text",
                mode="text",
                available=True,
            ),
            "txt": DeepDocParserSpec(
                parser_id="txt",
                file_type="txt",
                mode="txt",
                available=True,
            ),
            "markdown": DeepDocParserSpec(
                parser_id="markdown",
                file_type="md",
                mode="markdown",
                available=True,
            ),
            "html": DeepDocParserSpec(
                parser_id="html",
                file_type="html",
                mode="html",
                available=True,
            ),
            "json": DeepDocParserSpec(
                parser_id="json",
                file_type="json",
                mode="json",
                available=True,
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
    def build_configs(cls, file_type: str, parser_id: str | None = None) -> tuple[DeepDocParser, dict]:
        spec = cls.resolve_parser_id(file_type, parser_id)
        parser = DeepDocParser()
        parsing_config = {}
        if spec.file_type == "pdf":
            if spec.mode in {"plain", "full"}:
                parsing_config["deepdoc_pdf_mode"] = spec.mode
            parsing_config["deepdoc_parser_id"] = spec.parser_id
        elif spec.parser_id not in {"docx", "epub", "excel", "ppt", "figure", "text"}:
            parsing_config["deepdoc_parser_id"] = spec.parser_id
        return parser, parsing_config
