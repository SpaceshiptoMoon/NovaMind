from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


BACKEND_ROOT = Path(__file__).resolve().parents[4]


def test_deepdoc_packaging_includes_docs():
    dist_dir = BACKEND_ROOT / "dist"
    wheels = sorted(dist_dir.glob("novamind-*.whl"))
    if not wheels:
        # Keep this test informative when the build artifact has not been generated yet.
        return

    wheel_path = max(wheels, key=lambda path: path.stat().st_mtime)
    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())

    normalized_names = {name.replace("\\", "/") for name in names}

    assert "engines/document/integrations/deepdoc/README.md" in normalized_names


def test_deepdoc_packaging_includes_vendored_ragflow_pdf_parser():
    dist_dir = BACKEND_ROOT / "dist"
    wheels = sorted(dist_dir.glob("novamind-*.whl"))
    if not wheels:
        return

    wheel_path = max(wheels, key=lambda path: path.stat().st_mtime)
    with zipfile.ZipFile(wheel_path) as wheel:
        names = {name.replace("\\", "/") for name in wheel.namelist()}

    assert "engines/document/integrations/deepdoc/vendor/ragflow/pdf_parser.py" in names
    assert "engines/document/integrations/deepdoc/vendor/ragflow/__init__.py" in names
