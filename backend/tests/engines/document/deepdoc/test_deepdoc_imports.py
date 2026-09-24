"""DeepDoc 门面导出契约：外部消费面只有 4 个生产符号 + 诊断入口。

deepdoc 包外部的生产消费方（document_loader / document_pipeline / health_check）
只允许通过门面拿 DeepDocEngine / DeepDocParser / DeepDocParseResult /
strip_position_tags；其余能力一律走深路径 import。解析器别名（TxtParser 等）
已随批次 F 门面收口删除——RAGFlowTxtParser 等真名直接从 parsers/ 子模块拿。
"""
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_deepdoc_facade_exports_production_surface_only():
    import novamind.engines.document.integrations.deepdoc as deepdoc

    assert deepdoc.__all__ == [
        "DeepDocEngine",
        "DeepDocParser",
        "DeepDocParseResult",
        "strip_position_tags",
    ]
    assert callable(deepdoc.strip_position_tags)
    assert deepdoc.DeepDocParseResult.__name__ == "DeepDocParseResult"


def test_deepdoc_removed_aliases_are_gone():
    import novamind.engines.document.integrations.deepdoc as deepdoc

    for gone in ("TxtParser", "DocxParser", "PdfParser", "RAGFlowPdfParser", "create_deepdoc_app"):
        assert not hasattr(deepdoc, gone), gone


def test_deepdoc_facade_does_not_force_optional_format_imports():
    """门面懒导出：import 包本身不触达 cv2/xgboost 等重依赖模块。"""
    import novamind.engines.document.integrations.deepdoc as deepdoc

    # 触发全部导出解析，仍不应抛 ImportError（懒 __getattr__ 逐符号 import）
    for name in deepdoc.__all__:
        getattr(deepdoc, name)


def test_deepdoc_runtime_parser_can_be_constructed_without_optional_format_imports():
    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import DeepDocParser

    parser = DeepDocParser()
    assert parser is not None
    assert "pdf" in parser.supported_extensions()


def test_deepdoc_pdf_parser_can_be_imported_without_vision_or_xgboost_runtime():
    from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser

    assert RAGFlowPdfParser.__name__ == "RAGFlowPdfParser"


def test_deepdoc_engine_can_be_constructed_without_optional_heavy_runtime_imports():
    from novamind.engines.document.integrations.deepdoc.core.engine import DeepDocEngine

    engine = DeepDocEngine()
    assert engine is not None
    assert "pdf" in engine.supported_extensions()


def test_deepdoc_capabilities_load_without_remote_parser_or_vision_runtime_import_failures():
    from novamind.engines.document.integrations.deepdoc.core.capabilities import (
        get_deepdoc_capabilities,
    )

    capabilities = get_deepdoc_capabilities()
    assert "pdf_modes" in capabilities
    assert "full" in capabilities["pdf_modes"]
