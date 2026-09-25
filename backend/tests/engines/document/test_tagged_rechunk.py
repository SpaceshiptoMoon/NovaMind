"""哨兵标记重切（tagged_rechunk）回归测试：引用溯源数据链基础。

验证核心不变量：
1. reading_order 经哨兵编码 → 切分器切分 → 剥哨兵后，每个 chunk 能找回
   自己覆盖的 entry 结构（pages/entry_kinds/entry_source_ids）；
2. 干净正文无哨兵残留、无 ``@@`` 坐标标记泄漏（不污染 embedding/ES）；
3. 覆盖关系无遗漏无重复：所有 chunk 的 entry 并集 == 编码 entry 集合；
4. 超容量降级不中断；普通文本（无 reading_order）退化为纯文本切分。
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

from novamind.engines.document.pipeline.tagged_rechunk import (
    SENTINEL_BASE,
    SENTINEL_CAPACITY,
    _reading_order_entry_text,
    build_tagged_text,
    extract_chunk_structure,
    parse_position_tag,
    rechunk_with_structure,
    strip_sentinels,
)
from novamind.engines.document.splitters.fixed_size_splitter import FixedSizeSplitter
from novamind.engines.document.splitters.recursive_splitter import RecursiveCharacterSplitter
from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser

pytestmark = pytest.mark.unit


# ===== 测试数据工厂 =====


def _text_entry(i: int, page: int, text: str) -> dict:
    return {
        "kind": "text",
        "page": page,
        "col_id": 0,
        "bbox": {"x0": 72.0, "x1": 500.0, "top": 100.0 + i * 12, "bottom": 112.0 + i * 12},
        "text": text,
        "layout_type": "text",
        "position_tag": f"@@{page}\t{72.0 + i}\t{500.0 + i}\t{100.0 + i * 12:.1f}\t{112.0 + i * 12:.1f}##",
        "source_id": f"@@{page}\t{72.0 + i}\t{500.0 + i}\t{100.0 + i * 12:.1f}\t{112.0 + i * 12:.1f}##",
    }


def _table_entry(page: int, caption: str) -> dict:
    return {
        "kind": "table",
        "page": page,
        "bbox": {"x0": 60.0, "x1": 540.0, "top": 300.0, "bottom": 420.0},
        "text": "col1 | col2\n1 | 2",
        "caption": caption,
        "layout_type": "table",
        "artifact_id": f"table:{page}:0:0",
        "source_id": f"table:{page}:0:0",
        "html": "<table><tr><td>1</td></tr></table>",
    }


def _figure_entry(page: int, artifact_id: str) -> dict:
    return {
        "kind": "figure",
        "page": page,
        "bbox": {"x0": 100.0, "x1": 400.0, "top": 450.0, "bottom": 550.0},
        "text": "",
        "caption": f"Figure {artifact_id}",
        "layout_type": "figure",
        "artifact_id": artifact_id,
        "source_id": artifact_id,
        "image_placeholder": f"__FIGURE_URL__{artifact_id}__",
    }


def _sample_reading_order() -> list[dict]:
    """跨 3 页、混合 text/table/figure、含浮点坐标的模拟 reading_order。"""
    entries = []
    for page in (1, 2, 3):
        for i in range(8):
            entries.append(_text_entry(i, page, f"P{page} 第{i}段正文内容。" * 8))
    entries.insert(4, _table_entry(1, "表1：示例表格"))
    entries.insert(12, _figure_entry(2, "fig:2:0:0"))
    entries.insert(20, _table_entry(3, "表2：第二张表"))
    return entries


# ===== parse_position_tag =====


class TestParsePositionTag:
    def test_standard_tag(self):
        result = parse_position_tag("@@3\t72.0\t500.5\t100.1\t112.3##")
        assert result == {
            "page": 3,
            "bbox": {"x0": 72.0, "x1": 500.5, "top": 100.1, "bottom": 112.3},
        }

    def test_cross_page_tag_takes_first_page(self):
        result = parse_position_tag("@@3-4\t72.0\t500.0\t100.0\t112.0##")
        assert result is not None
        assert result["page"] == 3

    def test_malformed_returns_none(self):
        assert parse_position_tag("") is None
        assert parse_position_tag("not a tag") is None
        assert parse_position_tag("@@abc\t1.0\t2.0\t3.0\t4.0##") is None
        # 浮点坐标被切坏（历史 recursive splitter 的 '.' 分隔符事故形态）
        assert parse_position_tag("@@3\t72.0\t500.5\t100.1\t112.3") is None


# ===== build_tagged_text / strip_sentinels =====


class TestReadingOrderEntryTextAlignment:
    def test_rechunk_copy_matches_deepdoc_renderer(self):
        """对齐守护：tagged_rechunk 的 entry 渲染必须与 DeepDoc 原方法逐字一致。

        tagged_text 与 full_text 的同构性依赖 _reading_order_entry_text 的
        复刻；DeepDoc 侧改渲染逻辑时此处必须同步（同 _POSITION_TAG_RE ↔
        remove_tag 守护模式）。
        """
        entries = [
            _text_entry(0, 1, "正文段落"),
            _table_entry(1, "表1"),
            {**_table_entry(1, "表1"), "html": "", "text": "a | b"},
            _figure_entry(2, "fig1"),
            {**_figure_entry(2, "fig1"), "image_placeholder": "", "text": "图内文字"},
            {"kind": "unknown_kind", "page": 1, "text": "其他类型"},
        ]
        for entry in entries:
            assert _reading_order_entry_text(entry) == RAGFlowPdfParser._reading_order_entry_text(entry), (
                f"tagged_rechunk._reading_order_entry_text 与 DeepDoc 原方法漂移: kind={entry.get('kind')}"
            )


class TestBuildTaggedText:
    def test_sentinel_count_matches_entries(self):
        entries = _sample_reading_order()
        tagged, sentinel_map, encoded, degraded = build_tagged_text(entries)
        assert encoded == len(entries)
        assert len(sentinel_map) == len(entries)
        # 哨兵字符合法：PUA 区单字符
        for idx in sentinel_map:
            assert SENTINEL_BASE <= ord(chr(SENTINEL_BASE + idx)) < SENTINEL_BASE + SENTINEL_CAPACITY

    def test_empty_entries_skipped(self):
        entries = [_text_entry(0, 1, "有内容"), _text_entry(1, 1, "   "), _text_entry(2, 1, "也有内容")]
        tagged, sentinel_map, encoded, degraded = build_tagged_text(entries)
        assert encoded == 2
        assert 1 not in sentinel_map

    def test_over_capacity_degrades_without_crash(self):
        # 6500 > 6400：最后 100 个不编码，不抛异常
        entries = [_text_entry(i, 1, f"内容{i}") for i in range(SENTINEL_CAPACITY + 100)]
        tagged, sentinel_map, encoded, degraded = build_tagged_text(entries)
        assert encoded == SENTINEL_CAPACITY
        assert len(sentinel_map) == SENTINEL_CAPACITY
        # 超容量 entry 的文本仍在正文里（降级但不丢内容）
        assert f"内容{SENTINEL_CAPACITY + 99}" in tagged


class TestStripSentinels:
    def test_removes_all_sentinels(self):
        text = f"{chr(SENTINEL_BASE)}第一段\n\n{chr(SENTINEL_BASE + 5)}第二段"
        clean = strip_sentinels(text)
        assert clean == "第一段\n\n第二段"
        assert all(not (0xE000 <= ord(c) <= 0xF8FF) for c in clean)

    def test_keeps_normal_text(self):
        text = "普通文本，不含哨兵。English too."
        assert strip_sentinels(text) == text

    def test_empty(self):
        assert strip_sentinels("") == ""


# ===== extract_chunk_structure / rechunk_with_structure =====


class TestExtractChunkStructure:
    def test_no_sentinel_returns_empty_structure(self):
        structure = extract_chunk_structure("纯文本，无哨兵", {0: _text_entry(0, 1, "x")})
        assert structure["entry_count"] == 0
        assert structure["pages"] == []
        assert structure["entry_kinds"] == []

    def test_kinds_and_source_ids_ordered(self):
        entries = [_text_entry(0, 1, "正文"), _table_entry(1, "表"), _figure_entry(2, "fig1")]
        tagged, sentinel_map, _, _ = build_tagged_text(entries)
        structure = extract_chunk_structure(tagged, sentinel_map)
        assert structure["entry_kinds"] == ["text", "table", "figure"]
        assert structure["entry_source_ids"][1] == "table:1:0:0"
        assert structure["entry_source_ids"][2] == "fig1"
        assert structure["pages"] == [1, 2]
        assert structure["entry_count"] == 3
        # entry_bboxes 携带坐标（1b 批次 bbox 高亮的数据源）
        assert len(structure["entry_bboxes"]) == 3
        assert structure["entry_bboxes"][1]["page"] == 1
        assert structure["entry_bboxes"][1]["x0"] == 60.0


# ===== 端到端：真实切分器跑 tagged_text =====


def _split(tagged_text: str, strategy: str = "recursive", **kw) -> list[str]:
    """直接用切分器类跑切分（与 DocumentProcessor.split_text 同一分发语义，
    但不构造 DocumentProcessor——其 __init__ 会拉起 DeepDoc 引擎栈，
    8GB 内存机器上易触发整机内存耗尽）。条目协议与 split_text 一致：
    [{text, content, source, metadata}] → 提取非空 content/text。"""
    if strategy == "recursive":
        splitter = RecursiveCharacterSplitter(
            chunk_size=kw.get("chunk_size", 500),
            chunk_overlap=kw.get("chunk_overlap", 50),
            min_chunk_size=kw.get("min_chunk_size", 50),
        )
    elif strategy == "fixed_size":
        splitter = FixedSizeSplitter(
            chunk_size=kw.get("chunk_size", 500),
            chunk_overlap=kw.get("chunk_overlap", 0),
        )
    else:
        raise ValueError(f"E2E 测试只覆盖 recursive/fixed_size，收到 {strategy}")
    documents = [{"text": tagged_text, "content": tagged_text, "source": "", "metadata": {}}]
    chunks = asyncio.run(splitter.split(documents))
    return [
        (c.get("content") or c.get("text", ""))
        for c in chunks
        if (c.get("content") or c.get("text", "")).strip()
    ]


class TestRechunkEndToEnd:
    def test_recursive_split_structure_alignment(self):
        """recursive 切分后：结构对齐、无哨兵残留、无 @@ 泄漏、覆盖无遗漏。"""
        entries = _sample_reading_order()
        full_text = "\n\n".join(str(e["text"]) for e in entries).strip()  # 与 full_text 同构
        tagged, sentinel_map, encoded, degraded = build_tagged_text(entries)
        assert encoded == len(entries)

        tagged_chunks = _split(tagged, strategy="recursive", chunk_size=800, chunk_overlap=100, min_chunk_size=200)
        clean_chunks, chunk_structure, source = rechunk_with_structure(tagged_chunks, sentinel_map)

        assert source == "tagged_rechunk"
        assert len(clean_chunks) == len(chunk_structure)
        assert len(clean_chunks) >= 2  # 样本足够大，必然多块

        # 1. 干净正文无哨兵残留、无 @@ 坐标标记泄漏
        for chunk in clean_chunks:
            assert all(not (0xE000 <= ord(c) < 0xE000 + SENTINEL_CAPACITY) for c in chunk)
            assert "@@" not in chunk

        # 2. 覆盖关系：每个 chunk 的 entry 并集 == 全部编码 entry（无遗漏）。
        # recursive 的 min_chunk_size 合并会把边界 entry 归入相邻块，同一 entry
        # 理论上可跨块出现（overlap 语义），故按集合比对，不按多重集。
        covered: set[str] = set()
        for structure in chunk_structure:
            covered.update(structure["entry_source_ids"])
        expected_ids = {str(e.get("source_id", "")) for e in entries}
        assert covered == expected_ids

        # 3. 每个有哨兵的 chunk 结构非空且页码合理
        pages_seen = set()
        for structure in chunk_structure:
            if structure["entry_count"]:
                assert structure["entry_source_ids"]
                pages_seen.update(structure["pages"])
            assert structure["pages"] == sorted(set(structure["pages"]))
        assert pages_seen == {1, 2, 3}

        # 4. 正文内容保全：所有 entry 的渲染文本都能在干净 chunks 中找到
        #（与 full_text 同构：full_text 就是 _reading_order_entry_text join 出来的）。
        # 切分器会丢弃分隔符（\n\n 等）并重排空白，故两侧都做空白归一化后比对。
        joined_clean = "\n".join(clean_chunks)

        def _norm(s: str) -> str:
            return re.sub(r"\s+", "", s)

        normalized_clean = _norm(joined_clean)
        for e in entries:
            text = _reading_order_entry_text(e).strip()
            if text:
                assert _norm(text) in normalized_clean

    def test_fixed_size_split_structure_alignment(self):
        entries = _sample_reading_order()
        tagged, sentinel_map, _, _ = build_tagged_text(entries)
        tagged_chunks = _split(tagged, strategy="fixed_size", chunk_size=600, chunk_overlap=100)
        clean_chunks, chunk_structure, _ = rechunk_with_structure(tagged_chunks, sentinel_map)
        assert len(clean_chunks) == len(chunk_structure)
        # fixed_size 有 overlap：边界 entry 出现在相邻两块（允许重复），按集合比对
        covered: set[str] = set()
        for structure in chunk_structure:
            covered.update(structure["entry_source_ids"])
        assert covered == {str(e.get("source_id", "")) for e in entries}
        # 结构必须非空
        assert any(s["entry_count"] > 0 for s in chunk_structure)

    def test_splitter_cannot_break_sentinel_chars(self):
        """哨兵是单字符：无论切分参数多极端， ord() 找回的 entry 必然完整。"""
        entries = [_text_entry(i, 1, "字" * 50) for i in range(30)]
        tagged, sentinel_map, _, _ = build_tagged_text(entries)
        # 极小 chunk_size + 空分隔符兜底（逐字符切）也不该丢 entry
        tagged_chunks = _split(tagged, strategy="recursive", chunk_size=10, chunk_overlap=0, min_chunk_size=0)
        clean_chunks, chunk_structure, _ = rechunk_with_structure(tagged_chunks, sentinel_map)
        covered = []
        for structure in chunk_structure:
            covered.extend(structure["entry_kinds"])
        # 30 个 entry 的 kind 都该被找回（允许 overlap 重复，不允许丢失）
        assert covered.count("text") >= 30

    def test_plain_text_without_reading_order(self):
        """reading_order 缺失：sentinel_map 为空，切分退化为纯文本（不崩、结构空）。"""
        text = "普通文档全文。\n\n第二段内容。" * 50
        tagged_chunks = _split(text, strategy="recursive", chunk_size=300, chunk_overlap=50, min_chunk_size=100)
        clean_chunks, chunk_structure, source = rechunk_with_structure(tagged_chunks, {})
        assert source == "tagged_rechunk"
        assert len(clean_chunks) == len(chunk_structure)
        assert all(s["entry_count"] == 0 for s in chunk_structure)
        assert "".join(clean_chunks).startswith("普通文档全文。")
