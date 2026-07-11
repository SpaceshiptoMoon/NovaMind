from __future__ import annotations

from pathlib import Path

import pytest

from src.shared.utils.deepdoc.upstream import (
    LOCAL_ADAPTATION_SOURCE_MAP,
    UPSTREAM_SOURCE_MAP,
    get_upstream_deepdoc_snapshot,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEEPDOC_ROOT = REPO_ROOT / "backend" / "src" / "shared" / "utils" / "deepdoc"
UPSTREAM_ROOT = REPO_ROOT / ".tmp_ragflow_upstream"


def _require_upstream_snapshot() -> None:
    if not UPSTREAM_ROOT.exists():
        pytest.skip("optional .tmp_ragflow_upstream snapshot is not present in this worktree")


def test_upstream_source_map_points_to_existing_vendored_and_upstream_paths():
    _require_upstream_snapshot()
    for local_path, upstream_path in UPSTREAM_SOURCE_MAP.items():
        assert (DEEPDOC_ROOT / local_path).exists(), local_path
        assert (UPSTREAM_ROOT / upstream_path).exists(), upstream_path


def test_local_adaptation_source_map_points_to_existing_files_and_upstream_origins():
    _require_upstream_snapshot()
    for local_path, upstream_path in LOCAL_ADAPTATION_SOURCE_MAP.items():
        assert (DEEPDOC_ROOT / local_path).exists(), local_path
        assert (UPSTREAM_ROOT / upstream_path).exists(), upstream_path


def test_upstream_snapshot_exposes_source_maps():
    snapshot = get_upstream_deepdoc_snapshot()

    assert snapshot["upstream_source_map"]["parser/pdf_parser.py"] == "deepdoc/parser/pdf_parser.py"
    assert snapshot["local_adaptation_source_map"]["ragflow_pdf_parser.py"] == "deepdoc/parser/pdf_parser.py"
    assert snapshot["local_adaptation_source_map"]["ragflow_docx_parser.py"] == "deepdoc/parser/docx_parser.py"
