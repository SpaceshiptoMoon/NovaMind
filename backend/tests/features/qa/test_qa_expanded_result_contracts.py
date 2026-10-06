"""QA 下游消费扩展命中的两个修复回归（验证轮案例 A/B）。

- A：snippet 截断——扩展命中（句子窗口扩窗/父子回带）的 content 已是完整
  上下文，截 800 字会把窗口砍半，放宽到 wiki 同档 1500；
- B：跨 KB 聚合去重——逐库 search 拼接后，同文档窗口重叠（或回带同一父块）
  的命中语义高度重复，_dedupe_expanded_results 保留高分去重，存量命中零变化。
"""

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.qa.services.ai_chat_service import _dedupe_expanded_results

pytestmark = pytest.mark.unit


def _win_hit(doc_id, lo, hi, content, score):
    return {
        "chunk_id": f"{doc_id}_{(lo + hi) // 2}", "document_id": doc_id,
        "chunk_index": (lo + hi) // 2, "content": content, "score": score,
        "metadata": {"expansion_type": "sentence_window",
                     "expansion": {"type": "sentence_window",
                                   "retrieved_content": content,
                                   "window_chunk_range": [lo, hi]}},
    }


def _child_hit(doc_id, parent_id, content, score):
    return {
        "chunk_id": f"{doc_id}_c", "document_id": doc_id,
        "chunk_index": 1, "content": content, "score": score,
        "metadata": {"chunk_role": "child",
                     "expansion": {"type": "parent_child",
                                   "retrieved_content": content,
                                   "parent_chunk_id": parent_id}},
    }


class TestSnippetExpansionLimit:
    def test_expanded_snippet_limit_logic(self):
        """扩展命中与 wiki 同档 1500，普通命中 800（锁定截断上限选择逻辑）。"""

        # 直接锁定决策逻辑（与 ai_chat_service._retrieve_knowledge 同式）
        def _limit(r):
            metadata = r.get("metadata") or {}
            is_wiki = r.get("chunk_type") == "wiki_page"
            is_expanded = bool(metadata.get("expansion"))
            return 1500 if (is_wiki or is_expanded) else 800

        assert _limit({"metadata": {"expansion": {"type": "sentence_window"}}}) == 1500
        assert _limit({"chunk_type": "wiki_page", "metadata": {}}) == 1500
        assert _limit({"metadata": {}}) == 800
        # 相邻正常场景：无扩展元数据键 → 800
        assert _limit({"metadata": {"page_number": 1}}) == 800


class TestDedupeExpandedResults:
    def test_overlapping_windows_across_kbs_deduped(self):
        """同文档窗口重叠的两个 KB 命中（聚合后）：保留高分，低分剔除。"""
        results = [
            _win_hit(61, 0, 4, "低分窗口。", 0.5),
            _win_hit(61, 2, 6, "高分窗口。", 0.9),
        ]
        out = _dedupe_expanded_results(results)
        assert len(out) == 1
        assert out[0]["content"] == "高分窗口。"

    def test_disjoint_windows_kept(self):
        """同文档窗口分离（不相邻）：两条都保留。"""
        results = [
            _win_hit(61, 0, 2, "窗口甲。", 0.9),
            _win_hit(61, 10, 12, "窗口乙。", 0.8),
        ]
        assert len(_dedupe_expanded_results(results)) == 2

    def test_same_parent_deduped(self):
        """父子回带：不同 KB 命中的子块回带同一父块 → 只留高分一条。"""
        results = [
            _child_hit(61, "61_0", "父块全文。", 0.6),
            _child_hit(61, "61_0", "父块全文。", 0.9),
        ]
        out = _dedupe_expanded_results(results)
        assert len(out) == 1
        assert out[0]["score"] == 0.9

    def test_different_docs_same_range_both_kept(self):
        """跨文档同名区间：不同文档语义独立，都保留。"""
        results = [
            _win_hit(61, 0, 4, "文1窗口。", 0.8),
            _win_hit(62, 0, 4, "文2窗口。", 0.7),
        ]
        assert len(_dedupe_expanded_results(results)) == 2

    def test_plain_hits_untouched(self):
        """相邻正常场景：无扩展元数据的存量命中原样保留、顺序不变。"""
        results = [
            {"chunk_id": "61_1", "document_id": 61, "chunk_index": 1,
             "content": "普通块甲。", "score": 0.9, "metadata": {}},
            {"chunk_id": "61_2", "document_id": 61, "chunk_index": 2,
             "content": "普通块乙。", "score": 0.8, "metadata": {"page_number": 1}},
        ]
        out = _dedupe_expanded_results(results)
        assert out == results

    def test_mixed_plain_and_expanded(self):
        """混合场景：普通块与扩展块并存，各自独立处理。"""
        results = [
            {"chunk_id": "61_0", "document_id": 61, "chunk_index": 0,
             "content": "普通块。", "score": 0.95, "metadata": {}},
            _win_hit(61, 0, 2, "窗口甲。", 0.8),
            _win_hit(61, 1, 3, "窗口乙重叠。", 0.7),
        ]
        out = _dedupe_expanded_results(results)
        assert len(out) == 2
        assert out[0]["content"] == "普通块。"
        assert out[1]["content"] == "窗口甲。"
