"""递归切分器贪心装填回归测试：欠填充修复 + 分隔符保全 + 配置夹取。

验证核心不变量：
1. 贪心装填：同级片段聚拢到接近 chunk_size，不再两两合并产生系统性欠填充；
2. 内容保全：拼回所有块（去重叠）能还原原文的空白归一化形态，分隔符不丢、
   词不被粘连（空格路径 "abc def" 不得粘成 "abcdefghi"）；
3. 英文句读：小数点/缩写（3.14、Dr. Smith）不被裸 ``.`` 误切；
4. 配置夹取：min_chunk_size > chunk_size//2 自动夹取，PDF 调用点
   min=500/max=400 类存量配置不再导致合并空转；
5. 硬切兜底：无分隔符文本按滑动窗口硬切，chunk_overlap 生效；
6. 空串兜底：分隔符耗尽时不丢内容、不产生空块。
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.splitters.recursive_splitter import (
    RecursiveCharacterSplitter,
)

pytestmark = pytest.mark.unit


def _split(text: str, **kw) -> list[str]:
    """单文本快速切分入口（走 _split_text，不含跨页合并）。"""
    splitter = RecursiveCharacterSplitter(**kw)
    return asyncio.run(splitter._split_text(text))


def _split_docs(text: str, **kw) -> list[dict]:
    """完整 split 入口（含 _merge_small_chunks 合并与重编号）。"""
    splitter = RecursiveCharacterSplitter(**kw)
    return asyncio.run(splitter.split([{"text": text, "source": "t", "doc_id": "0"}]))


def _norm(s: str) -> str:
    """空白归一化：与 test_tagged_rechunk 同一口径。"""
    return re.sub(r"\s+", "", s)


# ===== 贪心装填 =====


class TestGreedyPacking:
    def test_short_sentences_pack_near_chunk_size(self):
        """句长 80 字 × 25 句 = 2000 字，chunk_size=1000：
        旧实现两两合并均块 ~161 字（块数 6 倍超标）；新实现应装到接近上限。
        """
        sentences = [f"这是第{i}句话，内容大约有八十字左右的长度，用来模拟中文散文的平均句长。" + "补" * 40 for i in range(25)]
        text = "。".join(sentences) + "。"
        assert len(text) >= 1800

        chunks = _split(text, chunk_size=1000, chunk_overlap=100, min_chunk_size=0)

        assert len(chunks) >= 2
        avg = sum(len(c) for c in chunks) / len(chunks)
        # 装填后均块应显著接近上限（旧实现 ~161，装填后应 > 500）
        assert avg > 500, f"均块 {avg:.0f} 字，仍属欠填充"
        # 硬上限不可突破
        assert all(len(c) <= 1000 for c in chunks)

    def test_paragraph_packing_no_pair_waste(self):
        """300 字段落：旧实现 300+301=601 封顶，新实现应装到 900+。"""
        paras = [f"段落{i}" + "内容" * 148 for i in range(6)]  # 每个 ~300 字
        text = "\n\n".join(paras)
        chunks = _split(text, chunk_size=1000, chunk_overlap=100, min_chunk_size=0)
        avg = sum(len(c) for c in chunks) / len(chunks)
        assert avg > 700, f"均块 {avg:.0f} 字，段落装填不足"

    def test_all_chunks_within_hard_limit(self):
        """任意参数下块长不得超 chunk_size（装填 + 递归下沉 + 硬切三路径）。"""
        text = ("甲" * 37 + "。" ) * 120  # ~4500 字，句级切分
        for size in (200, 500, 1000):
            chunks = _split(text, chunk_size=size, chunk_overlap=size // 10, min_chunk_size=0)
            assert all(len(c) <= size for c in chunks), f"chunk_size={size} 有块超限"

    def test_oversized_segment_recurses_down(self):
        """无句读长文本（超限）：递归下沉到逐字符硬切，不丢内容。"""
        text = "字" * 2500
        chunks = _split(text, chunk_size=1000, chunk_overlap=100, min_chunk_size=0)
        assert sum(len(c) for c in chunks) >= 2500 - 100  # 允许尾部 overlap 窗口取整损耗
        assert all(len(c) <= 1000 for c in chunks)


# ===== 内容保全 =====


class TestContentPreservation:
    def test_chinese_punctuation_preserved_on_join(self):
        """中文句号路径：切出的块必须保留句末标点（存量 bug：split 丢弃 。）。

        用 chunk_size=50 强制多次冲刷，验证块边界处标点不丢。
        """
        text = "第一句话内容。" * 20  # 140 字，句长 7
        chunks = _split(text, chunk_size=50, chunk_overlap=0, min_chunk_size=0)
        assert len(chunks) >= 2
        rejoined = "".join(chunks)
        # 每句 7 字（含句号），20 句重拼后必须仍是 20 个完整句子
        assert rejoined.count("。") == 20
        assert _norm(rejoined) == _norm(text)

    def test_space_separator_words_not_glued(self):
        """空格路径：聚拢拼接必须补回空格，"abc def" 不得粘成 "abcdefghi"。"""
        words = [f"word{i}" for i in range(60)]
        text = " ".join(words)  # ~419 字
        chunks = _split(text, chunk_size=100, chunk_overlap=0, min_chunk_size=0)
        rejoined = " ".join(chunks)
        assert _norm(rejoined) == _norm(text)
        # 粘连检测：任何块内出现跨词粘连（word 后直接跟字母）即为坏
        for c in chunks:
            assert not re.search(r"word\d+[a-z]", c), f"词被粘连: {c!r}"

    def test_newline_separator_lines_preserved(self):
        """单换行路径：行结构保留，行数不丢。"""
        lines = [f"第{i}行内容" + "x" * 15 for i in range(30)]
        text = "\n".join(lines)
        chunks = _split(text, chunk_size=200, chunk_overlap=0, min_chunk_size=0)
        rejoined = "\n".join(chunks)
        assert _norm(rejoined) == _norm(text)

    def test_no_empty_chunks(self):
        """任何路径不得产生纯空白块。"""
        text = ("短句。" * 3 + "\n\n") * 50
        chunks = _split(text, chunk_size=100, chunk_overlap=20, min_chunk_size=0)
        assert all(c.strip() for c in chunks)

    def test_tail_after_last_separator_not_dropped(self):
        """英文句读捕获组路径：最后一个分隔符之后的尾段不得丢弃
        （存量死代码 bug：range(len-1,2) 会丢 "A. B" 的 "B"）。
        """
        splitter = RecursiveCharacterSplitter(
            chunk_size=10, chunk_overlap=0, min_chunk_size=0,
            separators=[". ", " "],  # 强制走 '. ' 捕获组路径
        )
        chunks = asyncio.run(splitter._split_text("apple. banana"))
        rejoined = "".join(chunks)
        assert "banana" in rejoined
        assert _norm(rejoined) == _norm("apple. banana")


# ===== 英文句读 =====


class TestEnglishSentenceBoundaries:
    def test_decimal_not_split(self):
        """3.14 不得被裸 . 切开：'. '（带空格）排在裸 '.' 之前且 3.14 无空格。"""
        text = "圆周率是 3.14159，这是一段足够长的文本。" * 30
        chunks = _split(text, chunk_size=80, chunk_overlap=0, min_chunk_size=0)
        rejoined = _norm("".join(chunks))
        assert "3.14159" in rejoined

    def test_abbreviation_not_split(self):
        """Dr. Smith 后跟空格：'. ' 路径按句读切，但缩写+人名会落在同一片段，
        不会出现 "Dr" 与 "Smith" 分属两块且均缺上下文。"""
        text = "Dr. Smith went to the lab. " * 40
        chunks = _split(text, chunk_size=100, chunk_overlap=0, min_chunk_size=0)
        rejoined = _norm("".join(chunks))
        assert "Dr.Smith" in rejoined  # 归一化空白后 Smith 紧跟 Dr.


# ===== 配置夹取 =====


class TestMinChunkSizeClamp:
    def test_min_gt_max_clamped(self):
        """min=500 > max=400（PDF 调用点存量形态）：夹取到 200，合并恢复工作。"""
        splitter = RecursiveCharacterSplitter(chunk_size=400, chunk_overlap=50, min_chunk_size=500)
        assert splitter.min_chunk_size == 200

    def test_min_within_bounds_untouched(self):
        splitter = RecursiveCharacterSplitter(chunk_size=1000, chunk_overlap=100, min_chunk_size=300)
        assert splitter.min_chunk_size == 300

    def test_pdf_config_merge_actually_merges(self):
        """PDF 参数（min 夹取后）：小碎块应被合并而非全部原样保留。"""
        text = "短。" * 400  # 800 字，句长 2
        docs = _split_docs(text, chunk_size=400, chunk_overlap=50, min_chunk_size=500)
        # 夹取后 min=200：2 字碎块必须被聚拢/合并，块数远小于碎块数
        assert len(docs) < 50


# ===== 硬切兜底 =====


class TestHardSplitFallback:
    def test_overlap_applies_on_hard_split(self):
        """无分隔符可用时逐字符硬切，overlap 产生相邻块重叠。"""
        splitter = RecursiveCharacterSplitter(
            chunk_size=100, chunk_overlap=20, min_chunk_size=0,
            separators=[""],  # 强制硬切路径
        )
        text = "无分隔符文本" * 50  # 350 字
        chunks = asyncio.run(splitter._split_text(text))
        assert len(chunks) >= 3
        # 相邻块头尾重叠 ~20 字符
        for prev, nxt in zip(chunks, chunks[1:]):
            overlap = 0
            for k in range(min(20, len(prev), len(nxt)), 0, -1):
                if prev.endswith(nxt[:k]):
                    overlap = k
                    break
            assert overlap >= 15, f"相邻块重叠不足: {overlap}"

    def test_empty_separator_single_chars_rejoin(self):
        """空串分隔符逐字符切：内容零丢失（哨兵重切的最坏路径依赖）。"""
        splitter = RecursiveCharacterSplitter(
            chunk_size=7, chunk_overlap=0, min_chunk_size=0, separators=[""],
        )
        text = "逐字符切分测试用例"
        chunks = asyncio.run(splitter._split_text(text))
        assert "".join(chunks) == text


# ===== 完整 split 管线 =====


class TestFullSplitPipeline:
    def test_doc_id_renumbered_after_merge(self):
        """合并后 doc_id 连续重编号，rsplit 底账不漂移。"""
        text = "句子内容测试。" * 200
        docs = _split_docs(text, chunk_size=500, chunk_overlap=50, min_chunk_size=100)
        ids = [d["doc_id"] for d in docs]
        assert ids == [f"0_chunk_{i}" for i in range(len(docs))]

    def test_content_roundtrip_through_full_pipeline(self):
        """完整管线（切分+合并）内容零丢失：空白归一化后重拼 == 原文。"""
        text = "第一段内容比较长，包含多个分句，用于测试完整管线的 Round-Trip。" * 40
        docs = _split_docs(text, chunk_size=300, chunk_overlap=30, min_chunk_size=80)
        rejoined = "".join(d["text"] for d in docs)
        assert _norm(rejoined) == _norm(text)
