"""解析能力描述符端点的聚合逻辑守护测试（批次 3）。

描述符（GET /spaces/{id}/knowledge-bases/parsing-descriptors）是前端 accept
映射、切分策略白名单、数值边界的单一来源——端点的三块构建逻辑在此锁定关键
事实：epub 必须出现在 text 格式列表（半接线复发的哨兵）、策略白名单与装配
注册表一致、数值边界与 schema 约束一致。
"""
from __future__ import annotations

import sys
import typing
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.pipeline.document_loader import DocumentRegistry
from novamind.features.knowledge_space.api.knowledge_base_routes import (
    _extract_parsing_strategies,
)
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    SplittingConfig,
    TextParsingConfig,
)
from novamind.features.knowledge_space.services.document_file_types import (
    MODALITY_TO_FILE_TYPES,
)

pytestmark = pytest.mark.unit


def _formats() -> dict[str, list[str]]:
    return {
        modality: sorted(f".{ext}" for ext in exts)
        for modality, exts in MODALITY_TO_FILE_TYPES.items()
    }


class TestFormats:
    def test_epub_in_text_formats(self):
        """半接线哨兵：epub 必须出现在 text 格式列表（曾解析支持但传不进来）。"""
        assert ".epub" in _formats()["text"]

    def test_all_modalities_present(self):
        assert set(_formats()) == {"text", "image", "video", "audio"}

    def test_formats_carry_leading_dot(self):
        assert all(ext.startswith(".") for exts in _formats().values() for ext in exts)


class TestStrategyExtraction:
    def test_pdf_has_three_strategies(self):
        strategies = _extract_parsing_strategies(TextParsingConfig.model_fields)
        assert strategies["pdf"] == ["default", "deepdoc", "external_ocr"]

    def test_common_text_types_default_and_deepdoc(self):
        strategies = _extract_parsing_strategies(TextParsingConfig.model_fields)
        for key in ("docx", "txt", "markdown", "html"):
            assert strategies[key] == ["default", "deepdoc"]

    def test_deepdoc_only_types(self):
        strategies = _extract_parsing_strategies(TextParsingConfig.model_fields)
        for key in ("excel", "ppt", "epub"):
            assert strategies[key] == ["deepdoc"], f"{key} 应为 deepdoc-only"


class TestSplittingLimits:
    def test_chunk_size_boundaries_match_schema(self):
        props = SplittingConfig.model_json_schema()["properties"]
        chunk = props["chunk_size"]
        assert chunk["minimum"] == 50 and chunk["maximum"] == 4000
        assert chunk["default"] == 1000

    def test_all_numeric_fields_have_boundaries(self):
        props = SplittingConfig.model_json_schema()["properties"]
        limited = {
            n for n, p in props.items()
            if "minimum" in p and "maximum" in p and "default" in p
        }
        assert {"chunk_size", "chunk_overlap", "window_size", "parent_chunk_size"} <= limited


class TestRegistryAlignment:
    def test_descriptor_strategies_match_registry(self):
        """端点输出的策略白名单 = 装配注册表（白名单单一事实源）。"""
        from novamind.engines.document.pipeline import splitter_factory

        assert sorted(DocumentRegistry.get_available_strategies()) == (
            splitter_factory.get_available_builder_strategies()
        )
