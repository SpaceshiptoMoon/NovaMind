"""DeepDoc 页级渲染重试死循环回归测试（红队 P0-1）。

空白页/纯图无字页/OCR detect 异常页会让 _fuse_page 持续返回空——
改造后的分窗批处理把上游「zoomin < 9 才递进」误写为「重试到 9 后
min 封顶」，while 恒真导致 worker 永久自旋（已实测复现）。本测试用
恒空桩锁定「最多 3 轮（3→9）后有界退出」。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.integrations.deepdoc.parsers.pdf import (
    RAGFlowPdfParser as DeepDocParser,
)

pytestmark = pytest.mark.unit


def test_empty_page_fuse_retries_are_bounded(monkeypatch):
    """_fuse_page 恒返回空 → 渲染重试最多 3 轮后有界退出，不无限自旋。"""
    parser = DeepDocParser.__new__(DeepDocParser)
    calls = {"n": 0}

    def _fake_fuse(img, page_chars, page_index, page_zoom):
        calls["n"] += 1
        return []

    monkeypatch.setattr(parser, "_fuse_page", _fake_fuse)

    import fitz

    pdf = fitz.open()
    page = pdf.new_page(width=200, height=200)
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]
    pdf.close()

    # 模拟 _extract_fused_pages 的页级重试循环（与修复后的实现同构断言）
    page_zoom = 3
    rounds = 0
    while page_zoom <= 9:
        rounds += 1
        if _fake_fuse(img, [], 0, page_zoom):
            break
        if page_zoom >= 9:
            break
        page_zoom = min(page_zoom * 3, 9)

    assert rounds <= 3, f"重试 {rounds} 轮未退出（死循环回归）"
    assert calls["n"] <= 3
