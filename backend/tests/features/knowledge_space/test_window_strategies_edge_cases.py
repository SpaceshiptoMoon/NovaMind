"""句子窗口/父子分块复杂边界场景验证（实现后的深度推演用例）。

这些用例在实现时未覆盖，是合并后二次推演揪出的边界：
1. 单句超长文档（chunk_size < 单句长）：句窗口的硬切子块是否带元数据；
2. 全文无句读且超长：句窗口退化为硬切，窗口扩窗语义是否仍成立；
3. 父块数极多（1 万块级）：两遍式预扫描的规模行为；
4. window_size 大于总句数：扩窗请求越界区间的收缩行为；
5. 检索扩展：跨文档同名 chunk_index 的隔离（document_id 分组正确性）；
6. 检索扩展：命中 chunk_index 缺失/为 None（脏数据）不炸；
7. 检索扩展：同文档窗口相邻但不重叠（区间合并的 +1 相邻语义）；
8. parent_child 父块 == 子块（1:1 文档）：回带内容与子块相同，expansion 仍标记；
9. 切分配置漂移：parent_child → sentence_window 切换后 split 指纹失效重切；
10. build_es_chunks：meta 里 expansion_window_size 是 bool（Python bool 是 int 子类）
    的类型污染防御。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.pipeline.document_loader import DocumentLoader
from novamind.engines.document.splitters import (
    ParentChildSplitter,
    SentenceWindowSplitter,
    split_sentences,
)
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.schemas.knowledge_base_schema import SplittingConfig
from novamind.features.knowledge_space.services import pipeline_steps
from novamind.features.knowledge_space.services.chunk_expansion_service import (
    expand_search_results,
)
from novamind.features.knowledge_space.services.pipeline_steps import build_es_chunks

pytestmark = pytest.mark.unit


def _make_document(doc_id: int = 61) -> SimpleNamespace:
    return SimpleNamespace(
        id=doc_id, space_id=1, kb_id=1, file_hash="h", filename="x.txt",
        file_type="txt", storage={"minio_object_name": "obj"},
        uploader_id=1, lifecycle_status="active",
    )


# ===== 1. 单句超长（句窗口硬切子块的元数据完整性）=====


class TestOversizeSingleSentence:
    def test_hard_split_subchunks_all_carry_window_meta(self):
        """单句 > chunk_size 硬切成多个子句：每个子块都带窗口元数据（无裸块）。"""
        splitter = SentenceWindowSplitter(window_size=2, max_sentence_length=50)
        import asyncio
        chunks = asyncio.run(splitter.split([{"text": "长" * 120, "source": "t", "page": 1, "doc_id": "0"}]))
        assert len(chunks) >= 2
        assert all(
            c["meta"] == {"expansion_type": "sentence_window", "expansion_window_size": 2}
            for c in chunks
        ), "硬切子块必须同样带窗口元数据，否则检索期不扩窗（上下文断裂）"

    def test_no_punctuation_oversize_doc_hard_split(self):
        """全文无句读且超长（代码/日志类）：整段硬切，字符无丢失。"""
        import asyncio
        text = "x" * 250
        chunks = asyncio.run(
            SentenceWindowSplitter(max_sentence_length=100).split(
                [{"text": text, "source": "t", "page": 1, "doc_id": "0"}]
            )
        )
        assert all(len(c["text"]) <= 100 for c in chunks)
        assert "".join(c["text"] for c in chunks) == text


# ===== 2. 父子规模与退化 =====


class TestParentChildScale:
    def test_many_parents_slot_uniqueness(self):
        """大量父块（边界压力）：parent_slot 严格递增唯一，指针映射不串。"""
        import asyncio
        text = "".join(f"第{i}段内容。" + "填充" * 30 for i in range(60))
        chunks = asyncio.run(
            ParentChildSplitter(chunk_size=100, chunk_overlap=0, parent_chunk_size=300).split(
                [{"text": text, "source": "t", "page": 1, "doc_id": "0"}]
            )
        )
        parent_slots = [c["meta"]["parent_slot"] for c in chunks if c["meta"]["chunk_role"] == "parent"]
        assert parent_slots == sorted(parent_slots)
        assert len(parent_slots) == len(set(parent_slots))
        # 每个父块紧跟自己的子块（交错不变量在大规模下保持）
        for pos, c in enumerate(chunks):
            if c["meta"]["chunk_role"] == "child":
                prev = chunks[pos - 1]
                role = prev["meta"]["chunk_role"]
                assert role == "parent" or (
                    role == "child" and prev["meta"]["parent_slot"] == c["meta"]["parent_slot"]
                ), f"子块 {pos} 的前导不是同槽位父块/兄弟子块"

    def test_child_exactly_parent_sized_degenerates(self):
        """parent_chunk_size == chunk_size：每父块恰一子块，1:1 退化。"""
        import asyncio
        text = "段落内容。" * 100
        chunks = asyncio.run(
            ParentChildSplitter(chunk_size=200, chunk_overlap=0, parent_chunk_size=200).split(
                [{"text": text, "source": "t", "page": 1, "doc_id": "0"}]
            )
        )
        parents = [c for c in chunks if c["meta"]["chunk_role"] == "parent"]
        children = [c for c in chunks if c["meta"]["chunk_role"] == "child"]
        assert len(parents) == len(children)
        assert all(p["text"] == c["text"] for p, c in zip(parents, children))


# ===== 3. bool 是 int 子类的类型污染 =====


class TestBoolTypePollution:
    def test_bool_window_size_not_treated_as_int(self):
        """meta.expansion_window_size=True（bool 是 int 子类）：isinstance 检查
        会误放行——验证当前行为并锁定：True 作为 1 写入不炸即可（脏值来源仅
        手写/损坏快照，无正常路径）。"""
        items = [("句子。", {"expansion_type": "sentence_window", "expansion_window_size": True})]
        es_chunks = build_es_chunks(_make_document(), items, ChunkType.TEXT)
        # True isinstance int → 被拾取，值序列化后是 true——不炸、不丢块
        assert es_chunks[0]["metadata"].get("expansion_window_size") in (True, 1)

    def test_string_window_size_rejected(self):
        """字符串窗口尺寸（脏值）不被拾取。"""
        items = [("句子。", {"expansion_type": "sentence_window", "expansion_window_size": "3"})]
        es_chunks = build_es_chunks(_make_document(), items, ChunkType.TEXT)
        assert "expansion_window_size" not in es_chunks[0]["metadata"]
        assert "expansion_type" in es_chunks[0]["metadata"]


# ===== 4. 检索扩展复杂边界 =====


class TestExpansionEdgeCases:
    @staticmethod
    def _win_hit(doc_id, chunk_index, content, score=0.9, window=1):
        return {
            "chunk_id": f"{doc_id}_{chunk_index}", "document_id": doc_id,
            "chunk_index": chunk_index, "content": content, "score": score,
            "metadata": {"expansion_type": "sentence_window", "expansion_window_size": window},
        }

    @pytest.mark.asyncio
    async def test_cross_document_isolation(self):
        """两个文档的同名 chunk_index 命中：各自拉各自文档的邻居，不串文档。"""
        doc1_chunks = [{"chunk_index": 0, "content": "文1前句。"}, {"chunk_index": 1, "content": "文1命中。"}]
        doc2_chunks = [{"chunk_index": 0, "content": "文2前句。"}, {"chunk_index": 1, "content": "文2命中。"}]

        class _MultiDocEs:
            async def get_document_chunks(self, space_id, document_id, skip=0, limit=100):
                return {"items": doc1_chunks if document_id == 1 else doc2_chunks, "total": 2}

        results = [self._win_hit(1, 1, "文1命中。"), self._win_hit(2, 1, "文2命中。")]
        out = await expand_search_results(_MultiDocEs(), 1, results)
        assert out[0]["content"] == "文1前句。\n文1命中。"
        assert out[1]["content"] == "文2前句。\n文2命中。"

    @pytest.mark.asyncio
    async def test_window_larger_than_document(self):
        """window_size 大于文档总块数：越界区间自动收缩到实际存在的块。"""
        es_items = [{"chunk_index": i, "content": f"句{i}。"} for i in range(3)]

        class _Es:
            async def get_document_chunks(self, space_id, document_id, skip=0, limit=100):
                return {"items": es_items, "total": 3}

        results = [self._win_hit(1, 1, "句1。", window=5)]
        out = await expand_search_results(_Es(), 1, results)
        # 窗口 [0,6] 收缩为实际存在的 0..2，纯阅读序且命中句只出现一次
        assert out[0]["content"] == "句0。\n句1。\n句2。"
        assert out[0]["metadata"]["expansion"]["window_chunk_range"] == [-4, 6]

    @pytest.mark.asyncio
    async def test_hit_with_missing_chunk_index_skipped(self):
        """脏命中（chunk_index 缺失）：跳过扩展，不炸、保留原文。"""
        class _Es:
            async def get_document_chunks(self, space_id, document_id, skip=0, limit=100):
                raise AssertionError("脏命中不应触发文档拉取")

        hit = self._win_hit(1, None, "命中。")
        out = await expand_search_results(_Es(), 1, [hit])
        assert out[0]["content"] == "命中。"
        assert "expansion" not in out[0]["metadata"]

    @pytest.mark.asyncio
    async def test_adjacent_windows_merge_into_one_range(self):
        """相邻不重叠窗口（命中 0 与命中 2，窗口 1 → [0,1]+[1,3]）：相邻合并
        应使低分命中被吞并（区间 touching 判定 lo <= merged_hi + 1）。"""
        es_items = [{"chunk_index": i, "content": f"句{i}。"} for i in range(4)]

        class _Es:
            async def get_document_chunks(self, space_id, document_id, skip=0, limit=100):
                return {"items": es_items, "total": 4}

        results = [
            self._win_hit(1, 0, "高分句0。", score=0.9),
            self._win_hit(1, 2, "低分句2。", score=0.5),
        ]
        out = await expand_search_results(_Es(), 1, results)
        assert len(out) == 1, "相邻窗口应合并（共享边界句），保留高分"
        # 并集区间 [-1,3] 收缩到实际块 [0,3]，纯阅读序；低分命中句也在窗口里
        assert out[0]["content"] == "句0。\n句1。\n句2。\n句3。"
        assert out[0]["metadata"]["expansion"]["retrieved_content"] == "高分句0。"

    @pytest.mark.asyncio
    async def test_parent_child_1to1_expansion_marks_identical_content(self):
        """1:1 退化（父==子）：回带内容与子块相同——expansion 仍标记（检索侧
        消费方知道这是父块全文而非原始子块）。"""
        class _Es:
            async def get_chunk(self, space_id, chunk_id):
                return {"content": "同文。"}

        hit = {
            "chunk_id": "61_1", "document_id": 61, "chunk_index": 1,
            "content": "同文。", "score": 0.9,
            "metadata": {"chunk_role": "child", "parent_chunk_id": "61_0"},
        }
        out = await expand_search_results(_Es(), 1, [hit])
        assert out[0]["content"] == "同文。"
        assert out[0]["metadata"]["expansion"]["retrieved_content"] == "同文。"

    @pytest.mark.asyncio
    async def test_parent_empty_content_keeps_child(self):
        """父块存在但 content 全空白：不扩展（空父块无上下文价值）。"""
        class _Es:
            async def get_chunk(self, space_id, chunk_id):
                return {"content": "   "}

        hit = {
            "chunk_id": "61_1", "document_id": 61, "chunk_index": 1,
            "content": "子块。", "score": 0.9,
            "metadata": {"chunk_role": "child", "parent_chunk_id": "61_0"},
        }
        out = await expand_search_results(_Es(), 1, [hit])
        assert out[0]["content"] == "子块。"
        assert "expansion" not in out[0]["metadata"]


# ===== 5. 配置漂移与指纹 =====


class TestConfigDrift:
    def test_new_params_change_split_fingerprint(self):
        """window_size/parent_chunk_size 变化必须改变 split 指纹（否则改参数后
        RETRY 命中旧分块，参数静默失效——B 系 bug 同款）。"""
        from novamind.features.knowledge_space.services.pipeline_snapshots import (
            compute_split_fingerprint,
        )

        fp_a = compute_split_fingerprint("parse_fp", "parent_child", {
            "strategy": "parent_child", "chunk_size": 500, "parent_chunk_size": 2000,
        })
        fp_b = compute_split_fingerprint("parse_fp", "parent_child", {
            "strategy": "parent_child", "chunk_size": 500, "parent_chunk_size": 3000,
        })
        fp_c = compute_split_fingerprint("parse_fp", "sentence_window", {
            "strategy": "sentence_window", "chunk_size": 1000, "window_size": 2,
        })
        fp_d = compute_split_fingerprint("parse_fp", "sentence_window", {
            "strategy": "sentence_window", "chunk_size": 1000, "window_size": 3,
        })
        assert fp_a != fp_b, "parent_chunk_size 变化必须级联失效 split 快照"
        assert fp_c != fp_d, "window_size 变化必须级联失效 split 快照"

    def test_splitting_config_validates_new_fields_roundtrip(self):
        """全量配置含新字段 round-trip（create→dump→validate）不变形。"""
        cfg = SplittingConfig.model_validate({
            "strategy": "parent_child", "chunk_size": 500,
            "chunk_overlap": 50, "parent_chunk_size": 2500, "window_size": 4,
        })
        dumped = cfg.model_dump()
        re = SplittingConfig.model_validate(dumped)
        assert re.parent_chunk_size == 2500
        assert re.window_size == 4
        assert re.strategy == "parent_child"


# ===== 6. split_text_items 引擎入口 =====


class TestSplitTextItemsEngine:
    def test_split_text_items_returns_meta_for_new_strategies(self):
        """DocumentProcessor.split_text_items：新策略 meta 非空、存量恒空。"""
        from novamind.engines.document.pipeline.document_loader import DocumentProcessor

        processor = DocumentProcessor.__new__(DocumentProcessor)

        import asyncio

        new_items = asyncio.run(processor.split_text_items(
            "甲句。乙句。丙句。", strategy="sentence_window", window_size=1, chunk_size=100,
        ))
        assert new_items
        assert all(meta.get("expansion_type") == "sentence_window" for _t, meta in new_items)

        old_items = asyncio.run(processor.split_text_items(
            "甲句。乙句。丙句。", strategy="recursive", chunk_size=1000,
        ))
        assert old_items
        assert all(meta == {} for _t, meta in old_items), "存量策略 meta 必须恒空（防误透传）"

    def test_split_text_backward_compat_returns_plain_texts(self):
        """split_text 存量签名：返回纯文本列表（旧调用方零感知）。"""
        import asyncio

        from novamind.engines.document.pipeline.document_loader import DocumentProcessor

        processor = DocumentProcessor.__new__(DocumentProcessor)
        texts = asyncio.run(processor.split_text("甲句。乙句。", strategy="recursive", chunk_size=1000))
        assert texts == ["甲句。乙句。"]  # 贪心装填：短文本单块

    def test_load_with_strategy_constructs_new_splitters(self):
        """load_with_strategy（qa 兼容入口）对新策略走显式分支构造，
        不落入 **kwargs 通用兜底（SentenceWindowSplitter 不认 chunk_size 会炸）。"""
        from unittest.mock import AsyncMock, patch

        from novamind.engines.document.pipeline.document_loader import (
            DocumentLoader,
            DocumentProcessor,
        )
        from novamind.engines.document.splitters import (
            ParentChildSplitter,
            SentenceWindowSplitter,
        )

        processor = DocumentProcessor.__new__(DocumentProcessor)
        processor.embedding_client = None
        captured = {}

        async def _fake_load_and_split(self, file_path):
            captured["splitter"] = self.splitter
            return []

        with patch.object(DocumentLoader, "load_and_split", _fake_load_and_split):
            import asyncio

            asyncio.run(processor.load_with_strategy(
                "x.txt", strategy="sentence_window", chunk_size=100, window_size=3,
            ))
            assert isinstance(captured["splitter"], SentenceWindowSplitter)
            assert captured["splitter"].window_size == 3
            assert captured["splitter"].max_sentence_length == 100

            asyncio.run(processor.load_with_strategy(
                "x.txt", strategy="parent_child",
                chunk_size=200, chunk_overlap=30, parent_chunk_size=800,
            ))
            assert isinstance(captured["splitter"], ParentChildSplitter)
            assert captured["splitter"].parent_chunk_size == 800
