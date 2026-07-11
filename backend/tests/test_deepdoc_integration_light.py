import sys
import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.features.knowledge_space.schemas.knowledge_base_schema import KnowledgeBaseConfig
from src.features.knowledge_space.services.knowledge_base_service import KnowledgeBaseService
from src.shared.integrations.deepdoc.core.engine import DeepDocEngine
from src.shared.integrations.deepdoc.core.models import DeepDocParseResult
from src.shared.utils.deepdoc.server import create_deepdoc_app
from src.shared.document_processing.pipeline import DocumentProcessor


def _build_minimal_pdf_bytes(text: str) -> bytes:
    stream = f"BT\n/F1 18 Tf\n72 100 Td\n({text}) Tj\nET".encode("latin-1")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n"
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\n"
            b"endobj\n"
        ),
        b"4 0 obj\n<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]

    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = [0]
    body = b""
    current = len(header)
    for obj in objects:
        offsets.append(current)
        body += obj
        current += len(obj)

    xref_start = len(header) + len(body)
    xref = [b"xref\n0 6\n", b"0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    trailer = (
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_start).encode("ascii")
        + b"\n%%EOF\n"
    )
    return header + body + b"".join(xref) + trailer


def test_knowledge_base_config_accepts_deepdoc_strategy():
    config = KnowledgeBaseConfig.model_validate(
        {
            "parsing": {"strategy": "deepdoc", "deepdoc_pdf_mode": "plain"},
            "splitting": {"strategy": "recursive"},
        }
    )

    dumped = config.model_dump(by_alias=True)
    assert dumped["parsing"]["text"]["pdf"]["strategy"] == "deepdoc"
    assert dumped["parsing"]["text"]["pdf"]["parser"] is None


def test_knowledge_base_service_accepts_all_deepdoc_vision_options():
    service = object.__new__(KnowledgeBaseService)

    service._validate_config_updates(
        {
            "parsing": {
                "strategy": "deepdoc",
                "deepdoc_parser_id": "pdf_paddleocr",
                "deepdoc_pdf_mode": "vision",
            }
        }
    )


def test_document_processor_uses_deepdoc_strategy(monkeypatch, tmp_path):
    doc_path = tmp_path / "sample.pdf"
    doc_path.write_bytes(b"%PDF-1.4\n")

    processor = DocumentProcessor()

    async def fake_parse(file_path, *, parsing_config=None, splitting_config=None):
        assert Path(file_path) == doc_path
        assert parsing_config["strategy"] == "deepdoc"
        assert splitting_config["chunk_size"] == 256
        return DeepDocParseResult(
            full_text="@@1\t0\t10\t0\t10##hello",
            chunks=["@@1\t0\t10\t0\t10##hello"],
            metadata={"parser": "deepdoc"},
        )

    monkeypatch.setattr(processor, "_deepdoc_parser", SimpleNamespace(parse=fake_parse))

    full_text, chunks = asyncio.run(
        processor.parse_document(
            doc_path,
            parsing_config={"strategy": "deepdoc"},
            splitting_config={"chunk_size": 256},
        )
    )

    assert full_text.startswith("@@1")
    assert chunks == ["@@1\t0\t10\t0\t10##hello"]


def test_document_processor_uses_deepdoc_parser_id(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(_build_minimal_pdf_bytes("Processor Parser ID"))

    processor = DocumentProcessor()

    async def fake_aparse_with_parser_id(**kwargs):
        assert kwargs["file_type"] == "pdf"
        assert kwargs["parser_id"] == "pdf_plain"
        assert Path(kwargs["file_path"]) == pdf_path
        return DeepDocParseResult(
            full_text="processor parser id",
            chunks=["processor parser id"],
            metadata={"parser": "deepdoc", "pdf_mode": "plain"},
        )

    monkeypatch.setattr(processor, "_deepdoc_engine", SimpleNamespace(aparse_with_parser_id=fake_aparse_with_parser_id))

    full_text, chunks = asyncio.run(
        processor.parse_document(
            pdf_path,
            parsing_config={"strategy": "deepdoc", "deepdoc_parser_id": "pdf_plain"},
            splitting_config={"chunk_size": 256},
        )
    )

    assert full_text == "processor parser id"
    assert chunks == ["processor parser id"]


def test_document_processor_runs_real_deepdoc_pdf_path(tmp_path):
    pdf_path = tmp_path / "real-deepdoc.pdf"
    pdf_path.write_bytes(_build_minimal_pdf_bytes("Real Processor DeepDoc"))

    processor = DocumentProcessor()
    result = asyncio.run(
        processor.parse_document_result(
            pdf_path,
            parsing_config={
                "strategy": "deepdoc",
                "deepdoc_parser_id": "pdf_plain",
            },
            splitting_config={"chunk_size": 256},
        )
    )

    assert "Real Processor DeepDoc" in result.full_text
    assert result.chunks
    assert result.metadata["parser"] == "deepdoc"
    assert result.metadata["parser_id"] == "pdf_plain"


def test_document_processor_parse_document_result_preserves_deepdoc_metadata(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(_build_minimal_pdf_bytes("Structured Chunk"))

    processor = DocumentProcessor()

    async def fake_parse(file_path, *, parsing_config=None, splitting_config=None):
        return DeepDocParseResult(
            full_text="structured full text",
            chunks=["chunk 1"],
            metadata={"parser": "deepdoc", "chunk_structure": [{"entry_kinds": ["text"], "pages": [1]}]},
        )

    monkeypatch.setattr(processor, "_deepdoc_parser", SimpleNamespace(parse=fake_parse))

    result = asyncio.run(
        processor.parse_document_result(
            pdf_path,
            parsing_config={"strategy": "deepdoc"},
            splitting_config={"chunk_size": 256},
        )
    )

    assert result.full_text == "structured full text"
    assert result.metadata["parser"] == "deepdoc"
    assert result.metadata["chunk_structure"][0]["entry_kinds"] == ["text"]


def test_deepdoc_server_parse_bytes_endpoint_works():
    class _FakeEngine:
        def describe_capabilities(self):
            return {"ok": True}

        async def aparse_with_parser_id(self, **kwargs):
            return DeepDocParseResult(
                full_text="hello",
                chunks=["hello"],
                metadata={"parser": "deepdoc", "file_type": kwargs["file_type"]},
            )

    app = create_deepdoc_app(engine=_FakeEngine())
    client = TestClient(app)
    response = client.post(
        "/parse-bytes",
        json={
            "content_base64": "aGVsbG8=",
            "file_type": "txt",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["full_text"] == "hello"
    assert payload["metadata"]["file_type"] == "txt"


def test_deepdoc_server_doctor_endpoint_works():
    class _FakeEngine:
        def describe_capabilities(self):
            return {"ok": True}

        def supported_extensions(self):
            return {"pdf", "txt"}

        def available_pdf_modes(self):
            return {"plain": {"available": True}}

        def runtime_dependencies(self):
            return {"pdfplumber": {"available": True}}

        def vision_model_status(self):
            return {"groups": {"ocr": {"available": False}}}

        def vision_health_status(self):
            return {"required_missing": ["cv2"], "optional_missing": ["xgboost"]}

        def text_concat_model_status(self):
            return {"available": False}

        def upstream_snapshot(self):
            return {"commit": "abc123"}

        def vision_smoke_check(self):
            return {"checks": [{"name": "vision", "ok": False}]}

        async def aparse_with_parser_id(self, **kwargs):
            return DeepDocParseResult(full_text="", chunks=[], metadata={})

    app = create_deepdoc_app(engine=_FakeEngine())
    client = TestClient(app)

    response = client.get("/doctor", params={"smoke": "true"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime_dependencies"]["pdfplumber"]["available"] is True
    assert payload["remediation"]["missing_required_vision_dependencies"] == ["cv2"]
    assert payload["remediation"]["text_concat_model_missing"] is True
    assert payload["vision_smoke_check"]["checks"][0]["ok"] is False


def test_deepdoc_engine_available_pdf_modes_exposed():
    engine = DeepDocEngine()
    modes = engine.available_pdf_modes()

    assert "plain" in modes
    assert "layout" in modes
    assert "vision" in modes
