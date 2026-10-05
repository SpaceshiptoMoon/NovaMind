"""分隔符切分器回归测试：字面量级联切分 + 默认空行 + 硬切/合并不变量。

验证核心不变量：
1. 分隔符丢弃：任何 chunk 不含分隔符本身（切分标记非内容）；
2. 级联语义：多分隔符全部生效（区别于 recursive 的首个命中即用）；
3. 默认回落：None/空列表/全空串项一律回落空行切分；
4. 超长段硬切：固定窗口 + overlap，复用 FixedSizeSplitter 的不变量；
5. 碎段合并：min_chunk_size 触发相邻合并、0 禁用、超半夹取；
6. doc_id 契约：``_delimiter_chunk_{i}`` 编号、合并后重编号；
7. 注册：DocumentRegistry 可按 'delimiter' 取到本切分器。
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
from novamind.engines.document.splitters import DelimiterSplitter

pytestmark = pytest.mark.unit


def _split_docs(text: str, **kw) -> list[dict]:
    """完整 split 入口（含硬切与碎段合并）。"""
    splitter = DelimiterSplitter(**kw)
    return asyncio.run(
        splitter.split([{"text": text, "source": "t", "page": 1, "doc_id": "0", "type": "markdown"}])
    )


# ===== 分隔符切分与丢弃 =====


class TestSeparatorSplit:
    def test_literal_separator_splits_and_discards(self):
        """正例：'---' 切多段且分隔符不进任何块（相邻正常场景：内容含 '-' 但不成对不误切）。"""
        text = "第一节 AAA\n---\n第二节 BBB\n---\n第三节 CCC"
        chunks = _split_docs(text, chunk_size=1000, min_chunk_size=0, separators=["---"])
        assert [c["text"] for c in chunks] == ["第一节 AAA", "第二节 BBB", "第三节 CCC"]
        assert all("---" not in c["text"] for c in chunks)
        # 不误伤：单横线内容原样保留
        text2 = "a - b\n---\nc"
        chunks2 = _split_docs(text2, chunk_size=1000, min_chunk_size=0, separators=["---"])
        assert "a - b" in [c["text"] for c in chunks2]

    def test_cascade_applies_all_separators(self):
        """多分隔符级联：'---' 与空行都是边界（first-match-wins 会漏 '---'，此用例锁级联语义）。"""
        text = "X\n\nY---Z\n\nW"
        chunks = _split_docs(text, chunk_size=1000, min_chunk_size=0, separators=["---", "\n\n"])
        assert [c["text"] for c in chunks] == ["X", "Y", "Z", "W"]

    def test_separator_substring_literal_match(self):
        """字面量匹配：分隔符含正则元字符时按字面量生效，不炸不歧义。"""
        text = "A(cut)B(cut)C"
        chunks = _split_docs(text, chunk_size=1000, min_chunk_size=0, separators=["(cut)"])
        assert [c["text"] for c in chunks] == ["A", "B", "C"]


# ===== 默认回落 =====


class TestDefaultSeparators:
    def test_none_defaults_to_blank_line(self):
        """None 未配置 → 按空行切（策略默认语义，区别于「用户没选不兜底」的模型/配置兜底）。"""
        chunks = _split_docs("P\n\nQ", chunk_size=1000, min_chunk_size=0, separators=None)
        assert [c["text"] for c in chunks] == ["P", "Q"]

    def test_empty_and_blank_items_normalized(self):
        """空列表与全空串项同样回落空行；空串项被过滤（空串分隔符=逐字符切分爆炸）。"""
        assert DelimiterSplitter(separators=[]).separators == ["\n\n"]
        assert DelimiterSplitter(separators=["", ""]).separators == ["\n\n"]
        # 混合：空串项过滤、非空项保留
        assert DelimiterSplitter(separators=["", "---"]).separators == ["---"]

    def test_whitespace_separator_preserved_no_strip(self):
        """空白类分隔符不被 strip 摧毁：'\\n\\n' strip 后即空串，逐项必须原样保留。"""
        assert DelimiterSplitter(separators=["\n\n"]).separators == ["\n\n"]


# ===== 超长段硬切 =====


class TestOversizeHardSplit:
    def test_oversize_segment_hard_split_no_oversize_chunks(self):
        """超长段固定窗口硬切：各块 <= chunk_size、内容无丢失。"""
        long_seg = "A" * 25
        chunks = _split_docs(long_seg, chunk_size=10, chunk_overlap=0, min_chunk_size=0)
        assert all(len(c["text"]) <= 10 for c in chunks)
        assert "".join(c["text"] for c in chunks) == long_seg

    def test_hard_split_overlap_shares_tail(self):
        """overlap 生效：相邻硬切块共享尾部（对照 test_fixed_size_splitter_overlap 口径）。"""
        chunks = _split_docs("0123456789ABCD", chunk_size=10, chunk_overlap=3, min_chunk_size=0)
        assert chunks[0]["text"] == "0123456789"
        assert chunks[1]["text"] == "789ABCD"

    def test_mixed_segments_hard_split_only_oversize(self):
        """混合场景：只有超长段走硬切，分隔符段保持原样。"""
        text = "short\n---\n" + "B" * 30
        chunks = _split_docs(text, chunk_size=10, chunk_overlap=0, min_chunk_size=0, separators=["---"])
        assert "short" in [c["text"] for c in chunks]
        assert all(c["text"] != ("B" * 30) for c in chunks)


# ===== 碎段合并 =====


class TestSmallChunkMerge:
    def test_small_chunk_merged_forward(self):
        """碎段并入相邻块且不超 chunk_size；doc_id 重编号保持 _delimiter_chunk_ 中缀连续。"""
        text = "short\n---\n" + "B" * 80
        chunks = _split_docs(text, chunk_size=100, chunk_overlap=0, min_chunk_size=50, separators=["---"])
        assert len(chunks) == 1
        assert "short" in chunks[0]["text"]
        assert chunks[0]["doc_id"] == "0_delimiter_chunk_0"

    def test_merge_disabled_when_zero(self):
        """min_chunk_size=0 禁用合并：碎段独立成块。"""
        text = "tiny\n---\n" + "B" * 80
        chunks = _split_docs(text, chunk_size=100, chunk_overlap=0, min_chunk_size=0, separators=["---"])
        assert [c["text"] for c in chunks] == ["tiny", "B" * 80]

    def test_min_clamped_to_half_chunk_size(self):
        """min_chunk_size > chunk_size//2 夹取（防合并条件永不满足）。"""
        assert DelimiterSplitter(chunk_size=1000, min_chunk_size=900).min_chunk_size == 500


# ===== 产出契约 =====


class TestOutputContract:
    def test_doc_id_delimiter_chunk_numbering(self):
        """doc_id 按 ``{原doc_id}_delimiter_chunk_{序号}`` 连续编号。"""
        chunks = _split_docs("A\n\nB\n\nC", chunk_size=1000, min_chunk_size=0)
        assert [c["doc_id"] for c in chunks] == ["0_delimiter_chunk_0", "0_delimiter_chunk_1", "0_delimiter_chunk_2"]
        assert all(c["type"] == "markdown" for c in chunks)

    def test_empty_segments_dropped(self):
        """连续分隔符产生的空段被丢弃，不产出空块。"""
        chunks = _split_docs("A\n---\n\n---\nB", chunk_size=1000, min_chunk_size=0, separators=["---"])
        assert [c["text"] for c in chunks] == ["A", "B"]


# ===== 注册 =====


class TestRegistry:
    def test_delimiter_registered(self):
        """DocumentRegistry 能按 'delimiter' 取到 DelimiterSplitter。"""
        assert DocumentRegistry.get_splitter_class("delimiter") is DelimiterSplitter
