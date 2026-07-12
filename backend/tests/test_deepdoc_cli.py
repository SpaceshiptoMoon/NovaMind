import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_ROOT = Path(__file__).resolve().parents[1]


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


def test_deepdoc_cli_capabilities():
    completed = subprocess.run(
        [sys.executable, "-m", "novamind.shared.knowledge.integrations.deepdoc", "capabilities"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert "pdf_modes" in payload
    assert "vision" in payload["pdf_modes"]


def test_deepdoc_cli_doctor():
    completed = subprocess.run(
        [sys.executable, "-m", "novamind.shared.knowledge.integrations.deepdoc", "doctor"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert "runtime_dependencies" in payload
    assert "vision_health" in payload
    assert "vision_model_status" in payload
    assert "text_concat_model_status" in payload
    assert "remediation" in payload
    assert "next_steps" in payload["remediation"]


def test_deepdoc_cli_doctor_smoke(monkeypatch, capsys):
    from novamind.shared.knowledge.integrations.deepdoc import __main__ as deepdoc_cli

    monkeypatch.setattr(
        deepdoc_cli,
        "DeepDocEngine",
        lambda: SimpleNamespace(
            supported_extensions=lambda: {"pdf", "txt"},
            available_pdf_modes=lambda: {"plain": {"available": True}},
            runtime_dependencies=lambda: {"pdfplumber": {"available": True}},
            vision_model_status=lambda: {"groups": {"ocr": {"available": True}}},
            vision_health_status=lambda: {"required_missing": [], "optional_missing": []},
            text_concat_model_status=lambda: {"available": True},
            upstream_snapshot=lambda: {"commit": "abc"},
            vision_smoke_check=lambda: {"checks": [{"name": "vision", "ok": True}]},
        ),
    )

    exit_code = deepdoc_cli.main(["doctor", "--smoke"])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert "vision_smoke_check" in payload
    assert payload["vision_smoke_check"]["checks"][0]["ok"] is True


def test_deepdoc_cli_prepare(monkeypatch, tmp_path):
    from novamind.shared.knowledge.integrations.deepdoc import __main__ as deepdoc_cli

    calls = []

    monkeypatch.setattr(
        deepdoc_cli,
        "DeepDocEngine",
        lambda: SimpleNamespace(
            download_vision_models=lambda group=None: calls.append(("vision", group)) or (tmp_path / "vision"),
            download_text_concat_model=lambda: calls.append(("text_concat", None)) or (tmp_path / "text_concat" / "updown_concat_xgb.model"),
        ),
    )

    exit_code = deepdoc_cli.main(["prepare", "--vision-group", "ocr", "--include-text-concat"])

    assert exit_code == 0
    assert calls == [("vision", "ocr"), ("text_concat", None)]


def test_deepdoc_cli_prepare_reports_download_failure(monkeypatch, capsys):
    from novamind.shared.knowledge.integrations.deepdoc import __main__ as deepdoc_cli

    monkeypatch.setattr(
        deepdoc_cli,
        "DeepDocEngine",
        lambda: SimpleNamespace(
            download_vision_models=lambda group=None: (_ for _ in ()).throw(RuntimeError("network timeout")),
            download_text_concat_model=lambda: None,
        ),
    )

    exit_code = deepdoc_cli.main(["prepare", "--vision-group", "ocr"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "deepdoc_prepare_failed" in captured.err
    assert "network timeout" in captured.err


def test_deepdoc_cli_parse_pdf(tmp_path):
    pdf_path = tmp_path / "cli.pdf"
    pdf_path.write_bytes(_build_minimal_pdf_bytes("CLI DeepDoc"))

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "novamind.shared.knowledge.integrations.deepdoc",
            "parse",
            str(pdf_path),
            "--parser-id",
            "pdf_plain",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["metadata"]["parser"] == "deepdoc"
    assert payload["metadata"]["parser_id"] == "pdf_plain"
    assert "CLI DeepDoc" in payload["full_text"]


def test_deepdoc_server_factory_importable():
    from uvicorn.importer import import_from_string

    factory = import_from_string("novamind.shared.knowledge.integrations.deepdoc.server.deepdoc_server:create_deepdoc_app")
    app = factory()

    assert app.title == "DeepDoc Parser Service"
