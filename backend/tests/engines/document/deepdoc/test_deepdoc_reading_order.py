"""Regression tests for DeepDoc PDF two-column reading order.

Reproduces the failure mode behind the scrambled ``full_text`` reported for a
two-column academic PDF: the paragraph merger sorted boxes by ``(page, x0, top)``
/ ``(page, top, x0)`` and ignored ``col_id``, so left/right column lines and
display-math fragments at varying x positions were interleaved out of vertical
reading order. The fix sorts by ``(page, col_id, top, x0)`` so each column is
read top-to-bottom before moving to the next column.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.integrations.deepdoc.parsers.pdf import (
    DeepDocPdfBox,
    RAGFlowPdfParser,
)
from novamind.engines.document.integrations.deepdoc.pdf_layout import PdfLayoutExtractor
from novamind.engines.document.integrations.deepdoc.updown_concat import (
    UpDownConcatMerger,
)

pytestmark = pytest.mark.unit


def _box(
    page: int,
    col_id: int,
    x0: float,
    top: float,
    text: str,
    *,
    layout_type: str = "text",
    layoutno: str = "",
) -> DeepDocPdfBox:
    """Build a minimal text box; x1/top geometry only needs to be self-consistent."""
    width = 200.0
    height = 12.0
    return DeepDocPdfBox(
        page=page,
        x0=x0,
        x1=x0 + width,
        top=top,
        bottom=top + height,
        text=text,
        col_id=col_id,
        layout_type=layout_type,
        layoutno=layoutno,
    )


def test_heuristic_merge_preserves_column_reading_order():
    """Left column lines must all precede right column lines, each in top order."""
    merger = UpDownConcatMerger()
    # Two-column page 1: left col (x0=80) and right col (x0=400), interleaved by top
    # to mimic the raw insertion order before merging.
    boxes = [
        _box(1, 0, 80.0, 100.0, "L1 left column first line"),
        _box(1, 1, 400.0, 100.0, "R1 right column first line"),
        _box(1, 0, 80.0, 200.0, "L2 left column second line"),
        _box(1, 1, 400.0, 200.0, "R2 right column second line"),
        _box(1, 0, 80.0, 300.0, "L3 left column third line"),
        _box(1, 1, 400.0, 300.0, "R3 right column third line"),
    ]
    merged = merger._heuristic_merge(boxes)
    texts = [b.text for b in merged if b.text.strip()]

    left = [t for t in texts if t.startswith("L")]
    right = [t for t in texts if t.startswith("R")]
    assert left == ["L1 left column first line", "L2 left column second line", "L3 left column third line"]
    assert right == ["R1 right column first line", "R2 right column second line", "R3 right column third line"]
    # Entire left column must come before the entire right column.
    first_right_idx = min(i for i, t in enumerate(texts) if t.startswith("R"))
    assert all(t.startswith("L") for t in texts[:first_right_idx])


def test_heuristic_merge_does_not_interleave_math_fragments():
    """Display-math fragments at varying x0 must not reorder body text by x0."""
    merger = UpDownConcatMerger()
    boxes = [
        _box(1, 0, 80.0, 100.0, "Intro line A"),
        _box(1, 0, 80.0, 200.0, "Intro line B"),
        # A math fragment sitting low on the page but at a small-ish x0 — under the
        # old (page, x0, top) sort this would jump ahead of Intro line B.
        _box(1, 0, 120.0, 500.0, "eq-fragment"),
        _box(1, 0, 80.0, 600.0, "Conclusion line"),
    ]
    merged = merger._heuristic_merge(boxes)
    texts = [b.text for b in merged if b.text.strip()]
    # Top order must be preserved within the single column.
    assert texts == ["Intro line A", "Intro line B", "eq-fragment", "Conclusion line"]


def test_build_reading_order_metadata_is_column_aware():
    """Chunk reading-order metadata must group by column before top."""
    boxes = [
        _box(1, 0, 80.0, 100.0, "L1"),
        _box(1, 1, 400.0, 100.0, "R1"),
        _box(1, 0, 80.0, 200.0, "L2"),
        _box(1, 1, 400.0, 200.0, "R2"),
    ]
    order = RAGFlowPdfParser._build_reading_order_metadata(boxes, [], [])
    texts = [e["text"] for e in order if e.get("kind") == "text"]
    assert texts == ["L1", "L2", "R1", "R2"]


def test_assign_column_wires_pdf_layout(monkeypatch):
    """_assign_column_boxes 应把 boxes 交给 PdfLayoutExtractor.assign_columns 并写回 col_id。"""

    parser = RAGFlowPdfParser.__new__(RAGFlowPdfParser)
    parser._layout_extractor = PdfLayoutExtractor.__new__(PdfLayoutExtractor)

    def fake_assign_columns(boxes, **kwargs):
        for box in boxes:
            box["col_id"] = 1 if box["x0"] > 200 else 0
        return boxes

    monkeypatch.setattr(parser._layout_extractor, "assign_columns", fake_assign_columns)

    boxes = [
        _box(1, 0, 80.0, 100.0, "left"),
        _box(1, 0, 400.0, 100.0, "right"),
    ]
    assigned = parser._assign_column_boxes(boxes)
    assert [b.col_id for b in assigned] == [0, 1]


def test_text_merge_horizontal_text_only():
    """同 col、同 layoutno、相邻 y 的文本碎片应横向合并；表格/图片 box 不参与。

    vendored _text_merge 在 self.boxes（dict 域）上运行，此处按桥后域构造实例状态。
    """
    parser = RAGFlowPdfParser.__new__(RAGFlowPdfParser)
    parser.mean_height = [10.0]
    parser.mean_width = [8.0]
    parser.is_english = False
    parser.page_cum_height = [0.0, 1e6]

    boxes = [
        _box(1, 0, 80.0, 100.0, "Hello ", layoutno="L1"),
        _box(1, 0, 300.0, 100.0, "world", layoutno="L1"),
        _box(1, 0, 80.0, 200.0, "Second line", layoutno="L2"),
        _box(1, 0, 80.0, 300.0, "table-cell", layout_type="table"),
    ]
    parser.boxes = parser._boxes_to_vendored_domain(boxes)
    parser._text_merge()
    texts = [b.text for b in parser._boxes_from_vendored_domain(parser.boxes)]
    assert "Hello world" in texts
    assert "Second line" in texts
    assert "table-cell" in texts
    assert texts.count("Hello world") == 1
    assert texts.count("Second line") == 1
    assert texts.count("table-cell") == 1


def test_box_to_dict_round_trip_preserves_layoutno():
    """DeepDocPdfBox.to_dict / from_dict 应保留 layoutno。"""
    box = _box(1, 0, 80.0, 100.0, "x", layoutno="layout-1")
    restored = DeepDocPdfBox.from_dict(box.to_dict())
    assert restored.layoutno == "layout-1"
    assert restored.page == box.page
    assert restored.x0 == box.x0


def test_updown_concat_preserves_layoutno():
    """UpDownConcatMerger 状态转换应保留 layoutno 字段。"""
    merger = UpDownConcatMerger()
    boxes = [_box(1, 0, 80.0, 100.0, "a", layoutno="L1")]
    merged = merger._heuristic_merge(boxes)
    assert merged[0].layoutno == "L1"


# ---------------------------------------------------------------------------
# 分栏稳定化（doc568 完整性调查：双栏正文页被聚成 4 栏，左右栏行级交错）
# ---------------------------------------------------------------------------


def _dict_boxes(page: int, x0: float, top: float, text: str = "t") -> dict:
    return {
        "page_number": page,
        "x0": x0,
        "x1": x0 + 180.0,
        "top": top,
        "bottom": top + 12.0,
        "text": text,
    }


def test_two_column_page_not_oversegmented():
    """清晰双栏 + 居中标题/表格行两个孤立框 → 聚 2 栏，不再因孤立框聚 4 栏。"""
    extractor = PdfLayoutExtractor()
    boxes = []
    for i in range(20):
        boxes.append(_dict_boxes(1, 50.0 + (i % 3) * 0.5, 100.0 + i * 14.0, "L"))
        boxes.append(_dict_boxes(1, 310.0 + (i % 3) * 0.5, 100.0 + i * 14.0, "R"))
    # 孤立框：居中标题 + 跨栏表格行（旧代码聚 4 栏的元凶）
    boxes.append(_dict_boxes(1, 150.0, 50.0, "Title"))
    boxes.append(_dict_boxes(1, 200.0, 420.0, "TableRow"))

    assigned = extractor.assign_columns(boxes, force=True)
    n_cols = {b["col_id"] for b in assigned}
    assert n_cols == {0, 1}, f"应聚 2 栏，got {sorted(n_cols)}"


def test_clear_three_column_structure_still_detected():
    """真实三栏结构 silhouette 提升显著 → 不被 margin 回退误伤。"""
    extractor = PdfLayoutExtractor()
    boxes = []
    for i in range(20):
        boxes.append(_dict_boxes(1, 40.0, 100.0 + i * 14.0, "c1"))
        boxes.append(_dict_boxes(1, 220.0, 100.0 + i * 14.0, "c2"))
        boxes.append(_dict_boxes(1, 400.0, 100.0 + i * 14.0, "c3"))

    assigned = extractor.assign_columns(boxes, force=True)
    n_cols = {b["col_id"] for b in assigned}
    assert n_cols == {0, 1, 2}, f"三栏应保持 3 栏，got {sorted(n_cols)}"


def test_per_page_fallback_to_global_when_divergent():
    """单页聚 4、全局多数 2 → 分歧页（框数充足）固定 k=global_cols 重聚。"""
    extractor = PdfLayoutExtractor()
    boxes = []
    # 页 1/2：清晰双栏
    for pg in (1, 2):
        for i in range(20):
            boxes.append(_dict_boxes(pg, 50.0, 100.0 + i * 14.0))
            boxes.append(_dict_boxes(pg, 310.0, 100.0 + i * 14.0))
    # 页 3：双栏 + 大量居中散框（构造能聚出 >global+1 栏的分布）
    for i in range(20):
        boxes.append(_dict_boxes(3, 50.0, 100.0 + i * 14.0))
        boxes.append(_dict_boxes(3, 310.0, 100.0 + i * 14.0))
    for i in range(8):
        boxes.append(_dict_boxes(3, 150.0 + (i % 4) * 40.0, 90.0 + i * 50.0, "iso"))

    assigned = extractor.assign_columns(boxes, force=True)
    by_page = {}
    for b in assigned:
        by_page.setdefault(b["page_number"], set()).add(b["col_id"])
    for pg in (1, 2, 3):
        assert len(by_page.get(pg, set())) <= 3, (
            f"页{pg} 栏数 {sorted(by_page.get(pg, set()))} 不应显著偏离全局双栏"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
