from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_deepdoc_package_lazy_exports_do_not_force_optional_format_imports():
    from novamind.shared.knowledge.integrations.deepdoc import DeepDocParseResult
    from novamind.shared.knowledge.integrations.deepdoc import build_doctor_payload
    from novamind.shared.knowledge.integrations.deepdoc import TxtParser

    assert DeepDocParseResult.__name__ == "DeepDocParseResult"
    assert callable(build_doctor_payload)
    assert TxtParser.__name__ == "RAGFlowTxtParser"


def test_deepdoc_top_level_exports_include_service_helpers():
    from novamind.shared.knowledge.integrations.deepdoc import create_deepdoc_app
    from novamind.shared.knowledge.integrations.deepdoc import download_deepdoc_dependencies

    assert callable(create_deepdoc_app)
    assert callable(download_deepdoc_dependencies)


def test_deepdoc_runtime_parser_can_be_constructed_without_optional_format_imports():
    from novamind.shared.knowledge.integrations.deepdoc.core.runtime_parser import DeepDocParser

    parser = DeepDocParser()
    assert parser is not None
    assert "pdf" in parser.supported_extensions()


def test_deepdoc_pdf_parser_can_be_imported_without_vision_or_xgboost_runtime():
    from novamind.shared.knowledge.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser

    assert RAGFlowPdfParser.__name__ == "RAGFlowPdfParser"


def test_deepdoc_engine_can_be_constructed_without_optional_heavy_runtime_imports():
    from novamind.shared.knowledge.integrations.deepdoc.core.engine import DeepDocEngine

    engine = DeepDocEngine()
    assert engine is not None
    assert "pdf" in engine.supported_extensions()


def test_deepdoc_capabilities_load_without_remote_parser_or_vision_runtime_import_failures():
    from novamind.shared.knowledge.integrations.deepdoc.core.capabilities import get_deepdoc_capabilities

    capabilities = get_deepdoc_capabilities()
    assert "pdf_modes" in capabilities
    assert "vision" in capabilities["pdf_modes"]
