"""build_es_chunks 关系元数据白名单与自定义放通的守护测试（批次 0 锁定 + 批次 2.6 决策落地）。

机制：白名单键（chunk_role / parent_slot / expansion_type / content_type /
section_slot / expansion_window_size / entry_kinds / pages / 音视频时间与质量
键）显式拾取进 ES metadata 顶层；**其余自定义键收进 ``metadata.custom``**
（批次 2.6 决策：放通而非丢弃——新切分器如 bbpe 的自有关系元数据历史上会被
静默剥掉、检索期扩展能力无声消失）。custom 经 sanitize 限长限键数防 ES
mapping 膨胀。
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

from novamind.features.knowledge_space.services.pipeline_steps import (
    _CUSTOM_META_MAX_JSON,
    _CUSTOM_META_MAX_KEYS,
    _CUSTOM_META_MAX_STR,
    _RESERVED_CHUNK_META_KEYS,
    build_es_chunks,
)

pytestmark = pytest.mark.unit


def _document() -> SimpleNamespace:
    return SimpleNamespace(
        id=7, space_id=1, kb_id=1, file_hash="h", file_type="txt",
        filename="a.txt", storage={}, lifecycle_status="active",
    )


def _build(chunk_items: list[tuple[str, dict[str, Any]]]) -> list[dict]:
    return build_es_chunks(_document(), chunk_items, "text", parse_metadata={}, frame_paths=None)


def _meta_of(chunks: list[dict], index: int = 0) -> dict[str, Any]:
    return chunks[index]["metadata"]


class TestWhitelistPickup:
    """正例：白名单键拾取到 metadata 顶层（检索期扩窗/回带依赖）。"""

    def test_parent_child_pointers(self):
        items = [
            ("父块", {"chunk_role": "parent", "parent_slot": 0}),
            ("子块", {"chunk_role": "child", "parent_slot": 0}),
        ]
        chunks = _build(items)
        child = _meta_of(chunks, 1)
        assert child["chunk_role"] == "child"
        assert child["parent_chunk_id"] == "7_0"
        assert child["expansion_type"] == "parent_child"
        # 白名单键不重复进 custom
        assert "custom" not in child or "chunk_role" not in child.get("custom", {})

    def test_sentence_window_meta(self):
        items = [("窗口块", {
            "expansion_type": "sentence_window", "expansion_window_size": 3,
        })]
        chunks = _build(items)
        meta = _meta_of(chunks)
        assert meta["expansion_type"] == "sentence_window"
        assert meta["expansion_window_size"] == 3

    def test_broken_slot_degrades_to_plain(self):
        """slot 断链（父块缺失）→ 无指针的普通块（能力缺失优于错误指针）。"""
        chunks = _build([("子块", {"chunk_role": "child", "parent_slot": 99})])
        meta = _meta_of(chunks)
        assert "parent_chunk_id" not in meta
        assert meta["chunk_role"] == "child"


class TestCustomMetaPassthrough:
    """批次 2.6 决策：非白名单键放通进 metadata.custom（不再静默丢弃）。"""

    def test_custom_splitter_meta_preserved(self):
        """假想新策略的自有关系元数据（bbpe_cluster_id）进 metadata.custom。"""
        items = [
            ("块甲", {"bbpe_cluster_id": 11, "bbpe_cluster_size": 4}),
            ("块乙", {"bbpe_cluster_id": 11, "bbpe_cluster_size": 4}),
        ]
        chunks = _build(items)
        custom = _meta_of(chunks, 0)["custom"]
        assert custom["bbpe_cluster_id"] == 11
        assert custom["bbpe_cluster_size"] == 4

    def test_scalar_truncated(self):
        long_text = "x" * 500
        chunks = _build([("块", {"note": long_text})])
        assert len(_meta_of(chunks)["custom"]["note"]) == _CUSTOM_META_MAX_STR

    def test_complex_value_serialized(self):
        chunks = _build([("块", {"clusters": [{"id": 1}, {"id": 2}]})])
        custom = _meta_of(chunks)["custom"]
        assert isinstance(custom["clusters"], str)
        assert '"id": 1' in custom["clusters"]

    def test_key_count_capped(self):
        meta = {f"key_{i}": i for i in range(_CUSTOM_META_MAX_KEYS + 10)}
        chunks = _build([("块", meta)])
        assert len(_meta_of(chunks)["custom"]) == _CUSTOM_META_MAX_KEYS

    def test_no_custom_key_when_all_reserved(self):
        chunks = _build([("块", {"chunk_role": "parent", "parent_slot": 0})])
        assert "custom" not in _meta_of(chunks)

    def test_reserved_keys_never_leak_into_custom(self):
        """保留键集合完备性：任何已显式消费的键不得重复出现在 custom。"""
        meta = {
            "chunk_role": "child", "parent_slot": 0, "expansion_type": "parent_child",
            "entry_kinds": ["text"], "pages": [1], "entry_count": 1,
            "start_time": 1.0, "end_time": 2.0, "confidence": 0.9, "speaker_id": "0",
        }
        chunks = _build([("块", meta)])
        top = _meta_of(chunks)
        custom = top.get("custom", {})
        overlap = set(custom) & _RESERVED_CHUNK_META_KEYS
        assert not overlap, f"保留键泄漏进 custom: {overlap}"


class TestNonIntSlotGuards:
    def test_non_int_parent_slot_not_written(self):
        """parent_slot 非整数（类型异常）→ 不写指针，不抛错。"""
        chunks = _build([("子块", {"chunk_role": "child", "parent_slot": "not-an-int"})])
        assert "parent_chunk_id" not in _meta_of(chunks)
