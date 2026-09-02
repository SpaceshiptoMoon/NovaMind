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

BACKEND_ROOT = Path(__file__).resolve().parents[1]
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
    """_assign_column 应把 boxes 交给 PdfLayoutExtractor.assign_columns 并写回 col_id。"""
    from novamind.engines.document.integrations.deepdoc.pdf_layout import PdfLayoutExtractor

    parser = RAGFlowPdfParser.__new__(RAGFlowPdfParser)
    parser._layout_extractor = PdfLayoutExtractor.__new__(PdfLayoutExtractor)

    def fake_assign_columns(boxes):
        for box in boxes:
            box["col_id"] = 1 if box["x0"] > 200 else 0
        return boxes

    monkeypatch.setattr(parser._layout_extractor, "assign_columns", fake_assign_columns)

    boxes = [
        _box(1, 0, 80.0, 100.0, "left"),
        _box(1, 0, 400.0, 100.0, "right"),
    ]
    assigned = parser._assign_column(boxes)
    assert [b.col_id for b in assigned] == [0, 1]


def test_text_merge_horizontal_text_only():
    """同 col、同 layoutno、相邻 y 的文本碎片应横向合并；表格/图片 box 不参与。"""
    parser = RAGFlowPdfParser.__new__(RAGFlowPdfParser)
    parser._layout_extractor = PdfLayoutExtractor.__new__(PdfLayoutExtractor)
    parser._assign_column = lambda boxes, zoomin=3: boxes

    boxes = [
        _box(1, 0, 80.0, 100.0, "Hello ", layoutno="L1"),
        _box(1, 0, 300.0, 100.0, "world", layoutno="L1"),
        _box(1, 0, 80.0, 200.0, "Second line", layoutno="L2"),
        _box(1, 0, 80.0, 300.0, "table-cell", layout_type="table"),
    ]
    merged = parser._text_merge(boxes)
    texts = [b.text for b in merged]
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
