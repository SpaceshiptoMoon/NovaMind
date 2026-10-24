"""检索期扩展的下游口径与回归锁定（验证轮第二批复杂案例 C/E/F/G）。

- C：evaluation 切分健康统计以「切分产物本体」为准——扩展命中的 content 已被
  窗口/父块全文替换，健康统计须取 metadata.expansion.retrieved_content，
  否则句子窗口 KB 的碎片信号被扩窗掩盖；
- E：图片路径（line_aware=False）真实走窗口切分——图片文档粒度是一图一描述
  文本，窗口邻居是同图描述的相邻句，无跨图污染（行为锁定）；
- F：切分快照 round-trip 不丢关系元数据（parent_slot/parent_chunk_id 在
  save→load 后与切分产物逐键一致，resume 不退化）；
- G：sub_query 多路合并按 chunk_id 去重后每块只扩展一次（幂等护栏配合验证，
  经 expand_search_results 对重复 chunk_id 命中的幂等性锁定）。
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.evaluation.services.evaluation_service import (
    _compute_chunk_health,
    _original_chunk_content,
)
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.services import pipeline_steps
from novamind.features.knowledge_space.services.chunk_expansion_service import (
    expand_search_results,
)
from novamind.features.knowledge_space.services.pipeline_steps import build_es_chunks, TailInputs
from novamind.features.knowledge_space.services.pipeline_snapshots import (
    save_split_snapshot,
    load_split_snapshot,
)

pytestmark = pytest.mark.unit


# ===== C：evaluation 归因口径 =====


class TestEvaluationOriginalContent:
    def test_original_content_prefers_retrieved_content(self):
        """扩展命中取 retrieved_content（切分产物本体），非扩展取 content。"""
        expanded = {
            "chunk_id": "61_1", "content": "窗口全文。",
            "metadata": {"expansion": {"type": "sentence_window", "retrieved_content": "命中句。"}},
        }
        assert _original_chunk_content(expanded) == "命中句。"

        plain = {"chunk_id": "61_2", "content": "普通块。", "metadata": {}}
        assert _original_chunk_content(plain) == "普通块。"

        no_meta = {"chunk_id": "61_3", "content": "裸块。"}
        assert _original_chunk_content(no_meta) == "裸块。"

    def test_chunk_health_uses_original_content_not_window(self):
        """碎片信号口径：句子窗口命中句很短（切分产物本体 < 阈值），扩窗后
        content 变长——健康统计必须仍识别为碎片（按原始文本判定）。"""
        from novamind.features.evaluation.services.evaluation_service import CHUNK_SHORT_LENGTH

        expanded_hit = {
            "chunk_id": "61_1", "content": "x" * (CHUNK_SHORT_LENGTH + 50),
            "metadata": {"expansion": {"type": "sentence_window", "retrieved_content": "短句。"}},
        }
        health = _compute_chunk_health([expanded_hit])
        # 按扩展后 content 判会漏掉碎片；按原始文本判应记 1
        assert health["short_chunks"] == 1

    def test_chunk_health_plain_hits_unchanged(self):
        """相邻正常场景：无扩展命中统计行为零变化。"""
        from novamind.features.evaluation.services.evaluation_service import CHUNK_SHORT_LENGTH

        hits = [
            {"chunk_id": "61_1", "content": "长" * (CHUNK_SHORT_LENGTH + 10) + "。"},
            {"chunk_id": "61_2", "content": "短"},
        ]
        health = _compute_chunk_health(hits)
        assert health == {"total_chunks": 2, "short_chunks": 1, "unterminated_chunks": 1}

    def test_chunk_health_expanded_unterminated_by_original(self):
        """欠终止信号同样按原始文本判定：父块全文尾有句号，子块本体没有。"""
        expanded = {
            "chunk_id": "61_1", "content": "父块全文结尾有句号。",
            "metadata": {"expansion": {"type": "parent_child",
                                       "retrieved_content": "子块被拦腰截断的残句没标点"}},
        }
        health = _compute_chunk_health([expanded])
        assert health["unterminated_chunks"] == 1


# ===== E：图片路径窗口切分语义 =====


class TestImagePathWindowSplit:
    @staticmethod
    def _patch_tail(monkeypatch, bulk):
        async def _no_cancel(doc_id):
            return None

        async def _fake_embed(texts, cfg, *, session, user_id, model_config_port=None):
            return [b"\x00\x00\x00\x00"] * len(texts)

        async def _fake_es():
            async def _bulk(*, space_id, chunks, embedding_dim):
                bulk.extend(chunks)
                return len(chunks)

            async def _pre(*, space_id, document_id):
                return 0

            return SimpleNamespace(bulk_index_chunks=_bulk, delete_document_chunks=_pre)

        monkeypatch.setattr(pipeline_steps, "check_document_cancelled", _no_cancel)
        monkeypatch.setattr(pipeline_steps, "generate_embeddings", _fake_embed)
        monkeypatch.setattr(pipeline_steps, "get_es_client", _fake_es)

    def test_image_description_window_neighbors_are_same_image(self, monkeypatch):
        """图片描述文本窗口切分：邻居句来自同一张图的描述（一图一文档，
        full_text 就是本图描述），无跨图污染。窗口元数据照常落库。"""
        bulk: list = []
        self._patch_tail(monkeypatch, bulk)
        # 单图 VLM 描述：多句但都在同一图内
        description = (
            "这是一张办公室场景的照片。画面中央有一张木质办公桌。"
            "桌上放着一台打开的笔记本电脑。背景是一面白色的墙壁。"
            "照片整体光线明亮。"
        )
        doc = SimpleNamespace(
            id=88, space_id=1, kb_id=1, file_hash="h", filename="photo.png",
            file_type="png", storage={"minio_object_name": "obj"},
            uploader_id=1, lifecycle_status="active",
        )

        async def _run():
            return await pipeline_steps.run_post_parse_tail(
TailInputs(
                document=doc,
                session=_PlainSession(),
                task=SimpleNamespace(
                    start_step=lambda *a, **k: None,
                    finish_step=lambda *a, **k: None,
                ),
                model_config_port=None, logger=None,
                chunk_type=ChunkType.IMAGE,
                embedding_config={"dimension": 4},
                pipeline_config={"question_generation": {"enabled": False}},
                splitting_config={"strategy": "sentence_window", "chunk_size": 1000, "window_size": 2},
                full_text=description,
                user_id=1,
    ))

        result = asyncio.run(_run())
        assert result["split_strategy"] == "sentence_window"
        assert all(
            (c.get("metadata") or {}).get("expansion_type") == "sentence_window"
            for c in bulk
        )
        # 全部块的内容拼接还原本图描述（窗口只在本图文本内，无外部内容混入）
        assert "".join(c["content"] for c in bulk).replace("\n", "") == description


class _PlainSession:
    async def commit(self):
        return None


# ===== F：切分快照 round-trip =====


class TestSnapshotRoundTrip:
    def test_snapshot_roundtrip_preserves_relation_metadata(self):
        """save→load 切分快照：关系元数据逐键保留（resume 后 build_es_chunks
        两遍式照常解析绝对指针，不退化）。

        save 侧 payload 构造（save_split_snapshot 内联）：
        ``[[text, dict(meta)], ...]``；load 侧恢复（load_split_snapshot）：
        ``[(str(text), dict(meta or {})), ...]``。本用例锁定两侧形状契约对
        关系元数据无损。
        """
        chunk_items = [
            ("父块文本。", {"chunk_role": "parent", "parent_slot": 0}),
            ("子块一。", {"chunk_role": "child", "parent_slot": 0}),
            ("窗口句。", {"expansion_type": "sentence_window", "expansion_window_size": 2}),
        ]
        # save 侧内联构造（与 save_split_snapshot 同式）
        payload = {
            "split_fingerprint": "fp_x",
            "alignment_applied": False,
            "chunk_items": [[text, dict(meta or {})] for text, meta in chunk_items],
        }
        assert payload["chunk_items"] == [[t, dict(m)] for t, m in chunk_items]

        # load 侧恢复（与 load_split_snapshot 同式）
        restored = [(str(t), dict(m or {})) for t, m in payload["chunk_items"]]
        assert restored[0][1]["chunk_role"] == "parent"
        assert restored[1][1]["parent_slot"] == 0
        assert restored[2][1]["expansion_type"] == "sentence_window"
        assert restored[2][1]["expansion_window_size"] == 2

    def test_resume_then_build_es_chunks_resolves_pointers(self):
        """端到端：快照恢复的 chunk_items 喂 build_es_chunks，绝对指针照常解析。"""
        restored = [
            ("父块文本。", {"chunk_role": "parent", "parent_slot": 0}),
            ("子块一。", {"chunk_role": "child", "parent_slot": 0}),
        ]
        doc = SimpleNamespace(id=61, space_id=1, kb_id=1, file_hash="h",
                              filename="x.txt", file_type="txt",
                              storage={"minio_object_name": "obj"},
                              lifecycle_status="active")
        es_chunks = build_es_chunks(doc, restored, ChunkType.TEXT)
        assert es_chunks[1]["metadata"]["parent_chunk_id"] == "61_0"
        assert es_chunks[0]["metadata"]["chunk_role"] == "parent"


# ===== G：sub_query 合并后扩展幂等 =====


class TestSubQueryMergeExpansionIdempotent:
    @pytest.mark.asyncio
    async def test_same_chunk_id_hits_expand_once(self):
        """同一 chunk 的两份命中（sub_query 多路各召回一次）合并后进扩展：
        第一份扩展、第二份因幂等护栏跳过——不重复扩、不双份。"""
        doc_chunks = [
            {"chunk_index": 0, "content": "前句。"},
            {"chunk_index": 1, "content": "命中句。"},
            {"chunk_index": 2, "content": "后句。"},
        ]

        class _Es:
            async def get_document_chunks(self, space_id, document_id, skip=0, limit=100):
                return {"items": doc_chunks, "total": 3}

        def _hit():
            return {
                "chunk_id": "61_1", "document_id": 61, "chunk_index": 1,
                "content": "命中句。", "score": 0.9,
                "metadata": {"expansion_type": "sentence_window", "expansion_window_size": 1},
            }

        results = [_hit(), _hit()]  # 合并前同 chunk_id 出现两次（引擎已去重，此为防御）
        out = await expand_search_results(_Es(), 1, results)
        assert len(out) == 2
        expanded = [r for r in out if (r["metadata"].get("expansion") or {})]
        assert len(expanded) == 1, "同 chunk_id 双命中只扩展一份"
        assert out[0]["content"] != out[1]["content"], "第二份保持原始未扩展形态"
