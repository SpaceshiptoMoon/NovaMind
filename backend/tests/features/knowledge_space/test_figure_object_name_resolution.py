"""figure 短文件名 → 完整 object name 还原的纯函数测试（代理端点安全门）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services.document_query_service import (
    resolve_figure_object_name,
)

pytestmark = pytest.mark.unit

_STORAGE = {"figures_object_dir": "spaces/1/kbs/2/documents/42/abc.pdf_figures"}


def test_resolves_short_file_to_full_object_name():
    assert resolve_figure_object_name(_STORAGE, "figure_1_page_0_10_1.png") == (
        "spaces/1/kbs/2/documents/42/abc.pdf_figures/figure_1_page_0_10_1.png"
    )


def test_rejects_path_traversal_and_nested_paths():
    """白名单拒绝 ../、子目录、反斜杠——拼接后必须仍在 figures 目录内。"""
    for bad in (
        "../spaces/other/doc.pdf",
        "figures/figure_x_1.png",
        "..\\windows\\evil.png",
        "figure_x_1.png/../../etc/passwd",
    ):
        assert resolve_figure_object_name(_STORAGE, bad) is None, bad


def test_rejects_non_figure_prefix_and_wrong_extension():
    for bad in ("secret.pdf", "figure_x_1.jpg", "figure_x_1.png.exe", "figures_x.png"):
        assert resolve_figure_object_name(_STORAGE, bad) is None, bad


def test_missing_anchor_returns_none():
    """旧文档（未重解析）无 figures_object_dir 锚点 → None（调用方 404）。"""
    assert resolve_figure_object_name({"minio_object_name": "x.pdf"}, "figure_a_1.png") is None
    assert resolve_figure_object_name({}, "figure_a_1.png") is None
    assert resolve_figure_object_name(None, "figure_a_1.png") is None


def test_empty_inputs_return_none():
    assert resolve_figure_object_name(_STORAGE, "") is None
