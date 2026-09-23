"""ES 索引 delete-before-write + 部分失败即抛（2026-09 链路审计 P1#4/P1#5 回归）。

P1#4：bulk_index_chunks 是按 chunk_id 的 upsert，指纹失效重建后分块数变少时，
旧 {doc}_{高序号} chunk 永久残留进检索（只有 REPROCESS/删除/取消清 ES，
RETRY 成功路径不清）。run_post_parse_tail 索引步骤前必须按文档 delete 一次。

P1#5：bulk 内部失败只计成功数不抛错，此前 indexed_count != 0 即 COMPLETED
（1000 块失败 10 块照样成功，缺失块永久无感知）。现在 indexed_count <
len(es_chunks) 必须抛 RuntimeError 让任务进失败/重试路径。
"""
from types import SimpleNamespace

import pytest

from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.services import pipeline_steps


class _FakeSession:
    async def commit(self):
        return None


def _make_document():
    return SimpleNamespace(
        id=42,
        space_id=7,
        kb_id=3,
        uploader_id=1,
        filename="a.md",
        file_type="md",
        file_hash="h" * 32,
        storage={},
    )


def _make_task():
    task = SimpleNamespace(
        start_step=lambda name: None,
        finish_step=lambda name, metrics=None: None,
    )
    return task


def _patch_common(monkeypatch, es_stub):
    async def _no_cancel(doc_id):
        return None

    async def _fake_embed(texts, emb_cfg, *, session, user_id, model_config_port=None):
        return [b"\x00"] * len(texts)

    async def _fake_es():
        return es_stub

    monkeypatch.setattr(pipeline_steps, "check_document_cancelled", _no_cancel)
    monkeypatch.setattr(pipeline_steps, "generate_embeddings", _fake_embed)
    monkeypatch.setattr(pipeline_steps, "get_es_client", _fake_es)


def _make_es_stub(delete_calls, bulk_success_count_fn):
    async def _pre_delete(*, space_id, document_id):
        delete_calls.append((space_id, document_id))
        return 0

    async def _bulk(*, space_id, chunks, embedding_dim):
        return bulk_success_count_fn(chunks)

    return SimpleNamespace(bulk_index_chunks=_bulk, delete_document_chunks=_pre_delete)


@pytest.mark.asyncio
async def test_index_step_deletes_old_chunks_before_write(monkeypatch):
    """索引前必须按 document_id delete-before-write（幂等防孤儿 chunk）。"""
    delete_calls: list = []
    es_stub = _make_es_stub(delete_calls, lambda chunks: len(chunks))
    _patch_common(monkeypatch, es_stub)

    await pipeline_steps.run_post_parse_tail(
        document=_make_document(),
        session=_FakeSession(),
        task=_make_task(),
        model_config_port=None,
        logger=None,
        chunk_type=ChunkType.TEXT,
        embedding_config={"dimension": 4},
        pipeline_config={"question_generation": {"enabled": False}},
        splitting_config={"strategy": "fixed_size", "chunk_size": 50, "chunk_overlap": 0},
        full_text="内容甲。" * 30,
        user_id=1,
    )
    assert delete_calls == [(7, 42)], "索引前未按 (space_id, document_id) 清旧分块"


@pytest.mark.asyncio
async def test_partial_bulk_failure_raises_instead_of_silent_success(monkeypatch):
    """bulk 部分失败（indexed < total）必须抛错，不得静默 COMPLETED。"""
    delete_calls: list = []
    # 3 块中只有 2 块成功
    es_stub = _make_es_stub(delete_calls, lambda chunks: max(0, len(chunks) - 1))
    _patch_common(monkeypatch, es_stub)

    with pytest.raises(RuntimeError, match="部分写入失败"):
        await pipeline_steps.run_post_parse_tail(
            document=_make_document(),
            session=_FakeSession(),
            task=_make_task(),
            model_config_port=None,
            logger=None,
            chunk_type=ChunkType.TEXT,
            embedding_config={"dimension": 4},
            pipeline_config={"question_generation": {"enabled": False}},
            splitting_config={"strategy": "fixed_size", "chunk_size": 50, "chunk_overlap": 0},
            full_text="内容乙。" * 30,
            user_id=1,
        )


@pytest.mark.asyncio
async def test_full_bulk_success_still_passes(monkeypatch):
    """全量写入成功路径不受影响（回归保护）。"""
    delete_calls: list = []
    es_stub = _make_es_stub(delete_calls, lambda chunks: len(chunks))
    _patch_common(monkeypatch, es_stub)

    result = await pipeline_steps.run_post_parse_tail(
        document=_make_document(),
        session=_FakeSession(),
        task=_make_task(),
        model_config_port=None,
        logger=None,
        chunk_type=ChunkType.TEXT,
        embedding_config={"dimension": 4},
        pipeline_config={"question_generation": {"enabled": False}},
        splitting_config={"strategy": "fixed_size", "chunk_size": 50, "chunk_overlap": 0},
        full_text="内容丙。" * 30,
        user_id=1,
    )
    assert result["indexed_count"] == result["chunk_count"] >= 1
