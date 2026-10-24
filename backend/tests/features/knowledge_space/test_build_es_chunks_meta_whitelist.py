"""build_es_chunks 关系元数据白名单的现状锁定测试（批次 0 安全网）。

白名单拾取是显式键名制：chunk_role / parent_slot / expansion_type /
content_type / section_slot / expansion_window_size / entry_kinds / pages 等
进入 ES metadata，**其余键静默丢弃**。这是扩展性审计确认的现状——新切分器
（审计中的假想 bbpe）若产出自有关系元数据（如 cluster_id），落库时会被无声
剥掉，检索期能力静默消失。批次 2.6 决策（放通白名单 + 截断）落地后，本文件
的负例断言应反转为「未知键保留」，届时同步改写并在注释中记录决策依据。
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
        id=7, space_id=1, kb_id=1, file_hash="h", file_type="txt",
        filename="a.txt", storage={}, lifecycle_status="active",
    )


def _meta_of(chunks: list[dict], index: int = 0) -> dict[str, Any]:
    return chunks[index]["metadata"]


class TestWhitelistPickup:
    """正例：白名单键正常拾取（现状行为的基线）。"""

    def test_parent_child_pointers(self):
        items = [
            ("父块", {"chunk_role": "parent", "parent_slot": 0}),
            ("子块", {"chunk_role": "child", "parent_slot": 0}),
        ]
        chunks = build_es_chunks(_document(), items, "text", parse_metadata={})
        child = _meta_of(chunks, 1)
        assert child["chunk_role"] == "child"
        assert child["parent_chunk_id"] == "7_0"
        assert child["expansion_type"] == "parent_child"

    def test_sentence_window_meta(self):
        items = [("窗口块", {
            "expansion_type": "sentence_window", "expansion_window_size": 3,
        })]
        chunks = build_es_chunks(_document(), items, "text", parse_metadata={})
        meta = _meta_of(chunks)
        assert meta["expansion_type"] == "sentence_window"
        assert meta["expansion_window_size"] == 3


class TestUnknownMetaDropped:
    """负例（现状锁定）：非白名单键静默丢弃——批次 2.6 的决策标的。"""

    def test_custom_splitter_meta_dropped(self):
        """假想新策略的自有关系元数据（bbpe_cluster_id）不会出现在 ES。"""
        items = [
            ("块甲", {"bbpe_cluster_id": 11, "bbpe_cluster_size": 4}),
            ("块乙", {"bbpe_cluster_id": 11, "bbpe_cluster_size": 4}),
        ]
        chunks = build_es_chunks(_document(), items, "text", parse_metadata={})
        for chunk in chunks:
            assert "bbpe_cluster_id" not in chunk["metadata"]
            assert "bbpe_cluster_size" not in chunk["metadata"]

    def test_non_int_parent_slot_not_written(self):
        """parent_slot 非整数（类型异常）→ 不写指针，不抛错。"""
        items = [("子块", {"chunk_role": "child", "parent_slot": "not-an-int"})]
        chunks = build_es_chunks(_document(), items, "text", parse_metadata={})
        assert "parent_chunk_id" not in _meta_of(chunks)

    def test_broken_slot_degrades_to_plain(self):
        """slot 断链（父块缺失）→ 无指针的普通块（能力缺失优于错误指针）。"""
        items = [("子块", {"chunk_role": "child", "parent_slot": 99})]
        chunks = build_es_chunks(_document(), items, "text", parse_metadata={})
        meta = _meta_of(chunks)
        assert "parent_chunk_id" not in meta
        assert meta["chunk_role"] == "child"
