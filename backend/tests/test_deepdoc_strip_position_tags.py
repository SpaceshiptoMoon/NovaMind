"""Regression test for DeepDoc position-tag leak into chunk text.

History: ``document_loader.parse_document_result`` (deepdoc branch) fed the
tagged ``full_text`` (carrying ``@@<page>\\t<x0>\\t<x1>\\t<top>\\t<bottom>##``
layout-coordinate markers) straight into ``split_text``, discarding the clean
structured chunks, so coordinate strings like
``@@1    52.5    426.8    76.1    88.6`` leaked into chunk content / embedding.

The canonical cleaner is now ``core.models.strip_position_tags``; the loader
calls it before rechunking.
"""

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.knowledge.integrations.deepdoc.core.models import (
    strip_position_tags,
)
from novamind.shared.knowledge.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser

pytestmark = pytest.mark.unit


def test_strip_position_tags_removes_layout_markers():
    text = "@@1\t52.5\t426.8\t76.1\t88.6##第一行正文\n@@2\t10.0\t20.0\t30.0\t40.0##第二行"
    cleaned = strip_position_tags(text)
    assert "@@" not in cleaned
    assert "##" not in cleaned
    assert "52.5" not in cleaned and "426.8" not in cleaned
    assert "第一行正文" in cleaned
    assert "第二行" in cleaned


def test_strip_position_tags_matches_user_reported_marker():
    """The exact marker shape from the bug report must be stripped (tabs rendered as spaces here)."""
    text = "@@1\t52.5\t426.8\t76.1\t88.6##"
    assert strip_position_tags(text) == ""


def test_strip_position_tags_preserves_plain_text():
    assert strip_position_tags("纯文本无标记") == "纯文本无标记"
    assert strip_position_tags("") == ""


def test_pdf_remove_tag_delegates_to_canonical():
    """RAGFlowPdfParser.remove_tag must stay in sync with the canonical cleaner."""
    text = "@@1\t52.5\t426.8\t76.1\t88.6##正文"
    assert RAGFlowPdfParser.remove_tag(text) == strip_position_tags(text) == "正文"