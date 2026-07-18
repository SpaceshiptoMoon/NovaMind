"""Regression tests for DeepDoc PDF two-column reading order.

Reproduces the failure mode behind the scrambled ``full_text`` reported for a
two-column academic PDF: the paragraph merger sorted boxes by ``(page, x0, top)``
/ ``(page, top, x0)`` and ignored ``col_id``, so left/right column lines and
display-math fragments at varying x positions were interleaved out of vertical
reading order. The fix sorts by ``(page, col_id, top, x0)`` so each column is
read top-to-bottom before moving to the next column.
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.knowledge.integrations.deepdoc.parsers.pdf import (
    DeepDocPdfBox,
    RAGFlowPdfParser,
)
from novamind.shared.knowledge.integrations.deepdoc.updown_concat import (
    UpDownConcatMerger,
)


def _box(page: int, col_id: int, x0: float, top: float, text: str) -> DeepDocPdfBox:
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])