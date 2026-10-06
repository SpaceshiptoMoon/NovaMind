"""hierarchical 策略的 build_es_chunks 元数据接线回归测试。

验证：
1. 特殊对象块解析章节锚点指针（section_slot → section_anchor_chunk_id 绝对 id）；
2. 正文锚点块自身不写指针（它是被指向的一方）；
3. content_type 全块透传进 ES metadata；
4. slot 断链（锚点缺失）→ 不写指针（能力缺失优于错误指针）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services.pipeline_steps import build_es_chunks

pytestmark = pytest.mark.unit


def _document() -> SimpleNamespace:
    return SimpleNamespace(
        id=42, space_id=1, kb_id=1, file_hash="h", file_type="md",
        filename="a.md", storage={}, lifecycle_status="active",
    )


def _build(chunk_items: list[tuple[str, dict[str, Any]]]) -> list[dict]:
    return build_es_chunks(
        _document(), chunk_items, "text", parse_metadata={}, frame_paths=None,
    )


def _sample_items() -> list[tuple[str, dict[str, Any]]]:
    """模拟 HierarchicalSplitter 产物：锚点 + 正文 + 代码块（同章节 slot=0）。"""
    meta = {"expansion_type": "hierarchical", "section_slot": 0}
    return [
        ("# A\n首段", {**meta, "content_type": "text"}),
        ("正文段", {**meta, "content_type": "text"}),
        ("```py\nx=1\n```", {**meta, "content_type": "code"}),
    ]


class TestHierarchicalChunkMeta:
    def test_special_object_gets_anchor_pointer(self):
        """特殊对象块写入 section_anchor_chunk_id，指向章节锚点的绝对 id。"""
        chunks = _build(_sample_items())
        code_chunk = next(c for c in chunks if c["metadata"].get("content_type") == "code")
        assert code_chunk["metadata"]["section_anchor_chunk_id"] == "42_0"

    def test_anchor_block_has_no_pointer(self):
        """正文锚点块自身不写指针（无 section_anchor_chunk_id 键）。"""
        chunks = _build(_sample_items())
        anchor = chunks[0]
        assert "section_anchor_chunk_id" not in anchor["metadata"]
        assert anchor["metadata"]["content_type"] == "text"

    def test_content_type_passthrough(self):
        """content_type 全块透传。"""
        chunks = _build(_sample_items())
        assert [c["metadata"]["content_type"] for c in chunks] == ["text", "text", "code"]

    def test_broken_slot_no_pointer(self):
        """反例：锚点缺失（slot 断链）→ 特殊对象不写指针，退化为普通块。"""
        items = [
            ("正文段", {"expansion_type": "hierarchical", "section_slot": 0, "content_type": "text"}),
            ("```py\nx=1\n```", {"expansion_type": "hierarchical", "section_slot": 5, "content_type": "code"}),
        ]
        chunks = _build(items)
        code_chunk = chunks[1]
        assert "section_anchor_chunk_id" not in code_chunk["metadata"]
        assert code_chunk["metadata"]["content_type"] == "code"

    def test_existing_strategies_unaffected(self):
        """相邻正常场景：无 meta 的存量 chunk 不被 hierarchical 逻辑污染。"""
        chunks = _build([("普通块", {})])
        assert "content_type" not in chunks[0]["metadata"]
        assert "expansion_type" not in chunks[0]["metadata"]
