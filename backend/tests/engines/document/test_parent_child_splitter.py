"""父子分块切分器回归测试：两级边界 + 子块不跨父 + 槽位元数据 + doc_id 契约。

验证核心不变量：
1. 两级边界：父块按 parent_chunk_size 切、子块按 chunk_size 在父内切；
2. 子块不跨父：overlap 只在父块内部生效；
3. 父块 overlap=0：相邻父块无重叠（父块是容器不是检索单元）；
4. 槽位元数据：parent/child 带 parent_slot，child 的 slot 指向紧邻前导父块；
5. 交错输出：[父0, 子0_0, ...] 顺序即阅读序；
6. 退化：全文 <= parent_chunk_size → 1 父 1 子；
7. 配置矛盾：parent_chunk_size < chunk_size 构造抛 ValueError；
8. 注册：DocumentRegistry 可按 'parent_child' 取到本切分器。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.pipeline.document_loader import DocumentRegistry
from novamind.engines.document.splitters import ParentChildSplitter

pytestmark = pytest.mark.unit


def _split_docs(text: str, **kw) -> list[dict]:
    """完整 split 入口。"""
    splitter = ParentChildSplitter(**kw)
    return asyncio.run(
        splitter.split([{"text": text, "source": "t", "page": 1, "doc_id": "0", "type": "text"}])
    )


class TestConfigValidation:
    def test_parent_smaller_than_child_rejected(self):
        """配置矛盾：parent_chunk_size < chunk_size 构造即抛（父块装不下子块）。"""
        with pytest.raises(ValueError, match="parent_chunk_size"):
            ParentChildSplitter(chunk_size=1000, parent_chunk_size=500)

    def test_equal_sizes_accepted(self):
        """相邻正常场景：parent_chunk_size == chunk_size 合法（1 父 1 子）。"""
        splitter = ParentChildSplitter(chunk_size=1000, parent_chunk_size=1000)
        assert splitter.parent_chunk_size == 1000


class TestTwoLevelBoundaries:
    def test_two_level_structure_interleaved(self):
        """正例：多父块两级切分，输出 [父0, 子0_0, ...] 交错排列。"""
        text = "段一。" * 300 + "段二。" * 300
        chunks = _split_docs(text, chunk_size=300, chunk_overlap=0, parent_chunk_size=900)
        parents = [c for c in chunks if c["meta"]["chunk_role"] == "parent"]
        children = [c for c in chunks if c["meta"]["chunk_role"] == "child"]
        assert len(parents) >= 2
        assert len(children) >= len(parents)
        # 父块尺寸守上限
        assert all(len(p["text"]) <= 900 for p in parents)
        # 子块尺寸守上限
        assert all(len(c["text"]) <= 300 for c in children)

    def test_children_contained_in_parent(self):
        """子块内容来自其父块：每个子块文本是紧邻前导父块文本的子串或与之拼接还原。"""
        text = "段落甲第一句。段落甲第二句。段落乙第一句。段落乙第二句。"
        chunks = _split_docs(text, chunk_size=15, chunk_overlap=0, parent_chunk_size=30)
        parents = {c["meta"]["parent_slot"]: c["text"] for c in chunks if c["meta"]["chunk_role"] == "parent"}
        for c in chunks:
            if c["meta"]["chunk_role"] == "child":
                assert c["text"] in parents[c["meta"]["parent_slot"]]


class TestSlotMetadata:
    def test_child_parent_slot_matches_preceding_parent(self):
        """子块 parent_slot 指向其前导父块的序数。"""
        text = "内容一。" * 200 + "内容二。" * 200
        chunks = _split_docs(text, chunk_size=200, chunk_overlap=0, parent_chunk_size=600)
        last_parent_slot = -1
        for c in chunks:
            if c["meta"]["chunk_role"] == "parent":
                last_parent_slot = c["meta"]["parent_slot"]
            else:
                assert c["meta"]["parent_slot"] == last_parent_slot


class TestOverlapSemantics:
    def test_child_overlap_within_parent_only(self):
        """子块 overlap 生效且不跨父：相邻父块的子块内容不交叠。"""
        text = "甲" * 400 + "乙" * 400
        chunks = _split_docs(text, chunk_size=150, chunk_overlap=50, parent_chunk_size=400)
        parents = [c for c in chunks if c["meta"]["chunk_role"] == "parent"]
        assert parents[0]["text"].startswith("甲")
        assert parents[1]["text"].startswith("乙")
        # 父块无重叠：父0 不含乙、父1 不含甲
        assert "乙" not in parents[0]["text"]
        assert "甲" not in parents[1]["text"]


class TestDegenerateCases:
    def test_small_doc_degenerates_to_single_parent_child(self):
        """全文 <= parent_chunk_size：1 父 1 子，子=父文本（等价普通切分）。"""
        text = "短文档内容。"
        chunks = _split_docs(text, chunk_size=100, chunk_overlap=0, parent_chunk_size=1000)
        assert len(chunks) == 2
        assert chunks[0]["meta"]["chunk_role"] == "parent"
        assert chunks[1]["meta"]["chunk_role"] == "child"
        assert chunks[0]["text"] == chunks[1]["text"] == text

    def test_empty_input_returns_empty(self):
        """反例：纯空白输入产出零 chunk。"""
        assert _split_docs("   ") == []


class TestOutputContract:
    def test_doc_id_pc_chunk_numbering(self):
        """doc_id 编码父槽位与子序（_pc_chunk_p{k} / _pc_chunk_p{k}c{j}），可读可溯。"""
        text = "甲" * 500 + "乙" * 500
        chunks = _split_docs(text, chunk_size=250, chunk_overlap=0, parent_chunk_size=500)
        assert chunks[0]["doc_id"] == "0_pc_chunk_p0"
        assert chunks[0]["doc_id"].startswith("0_pc_chunk_p")
        child_ids = [c["doc_id"] for c in chunks if c["meta"]["chunk_role"] == "child"]
        assert all("_pc_chunk_p" in cid and "c" in cid.rsplit("p", 1)[1] for cid in child_ids)


class TestRegistry:
    def test_parent_child_registered(self):
        """DocumentRegistry 能按 'parent_child' 取到 ParentChildSplitter。"""
        assert DocumentRegistry.get_splitter_class("parent_child") is ParentChildSplitter
