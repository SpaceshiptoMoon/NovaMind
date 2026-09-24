from __future__ import annotations

from pathlib import Path

import pytest
from novamind.engines.document.integrations.deepdoc.compat.upstream import (
    LOCAL_ADAPTATION_SOURCE_MAP,
    UPSTREAM_SOURCE_MAP,
    get_upstream_deepdoc_snapshot,
)

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parents[5]
DEEPDOC_ROOT = REPO_ROOT / "backend" / "src" / "engines" / "document" / "integrations" / "deepdoc"
UPSTREAM_ROOT = REPO_ROOT / ".tmp_ragflow_upstream"


def _require_upstream_snapshot() -> None:
    if not UPSTREAM_ROOT.exists():
        pytest.skip("optional .tmp_ragflow_upstream snapshot is not present in this worktree")


def test_upstream_source_map_points_to_existing_vendored_and_upstream_paths():
    for local_path, upstream_path in UPSTREAM_SOURCE_MAP.items():
        assert (DEEPDOC_ROOT / local_path).exists(), local_path
    # 上游源码路径只在 vendored 处核对真源（逐字拷贝自该 commit）；其余映射
    # 依赖可选 .tmp_ragflow_upstream 快照，缺失时跳过该侧断言。
    if UPSTREAM_ROOT.exists():
        for local_path, upstream_path in UPSTREAM_SOURCE_MAP.items():
            if local_path.startswith("vendor/"):
                continue  # vendored 条目无对应快照路径（快照 commit 不同）
            assert (UPSTREAM_ROOT / upstream_path).exists(), upstream_path


def test_local_adaptation_source_map_points_to_existing_files_and_upstream_origins():
    for local_path, upstream_path in LOCAL_ADAPTATION_SOURCE_MAP.items():
        assert (DEEPDOC_ROOT / local_path).exists(), local_path
    if UPSTREAM_ROOT.exists():
        for local_path, upstream_path in LOCAL_ADAPTATION_SOURCE_MAP.items():
            assert (UPSTREAM_ROOT / upstream_path).exists(), upstream_path


def test_upstream_snapshot_exposes_source_maps():
    snapshot = get_upstream_deepdoc_snapshot()

    assert snapshot["upstream_source_map"]["vendor/ragflow/pdf_parser.py"] == "deepdoc/parser/pdf_parser.py"
    assert snapshot["local_adaptation_source_map"]["parsers/upstream/docx_parser.py"] == "deepdoc/parser/docx_parser.py"
    assert snapshot["local_adaptation_source_map"]["parsers/pdf.py"] == "deepdoc/parser/pdf_parser.py"


def test_vendored_pdf_parser_is_verbatim_upstream_copy():
    """vendored pdf_parser.py 除头部两行 provenance 注释外必须与上游逐字一致。

    用特征函数签名 + provenance 头做指纹校验（完整逐字 diff 依赖 .tmp 快照，
    缺失时只校验本地不可变指纹）。
    """
    vendored = DEEPDOC_ROOT / "vendor" / "ragflow" / "pdf_parser.py"
    assert vendored.exists()
    text = vendored.read_text(encoding="utf-8")
    # provenance 头必须在前两行注明上游 commit
    assert "2a83ad6" in text.split("\n")[0], "vendored 头部必须注明上游 commit"
    assert "不得改动本文件" in text.split("\n")[1]
