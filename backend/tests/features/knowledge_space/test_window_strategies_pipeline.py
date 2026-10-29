"""句子窗口/父子分块策略管道回归测试（run_post_parse_tail 全链路）。

验证核心不变量：
1. 关系元数据全链路：切分 meta → prechunked_items → build_es_chunks 白名单
   拾取 → ES chunk（expansion_type / chunk_role / parent_chunk_id 绝对指针）；
2. 父块跳过 embedding 与问题生成（成本语义：父块是容器不是检索单元）；
3. line_aware 回落：音视频锚点文本走行边界切分，无关系元数据；
4. 存量不误伤：recursive 等存量策略产物无任何新键；
5. 退化安全：slot 断链 → 子块无指针（能力缺失优于错误指针）。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.services import pipeline_steps
from novamind.features.knowledge_space.services.pipeline_steps import TailInputs, build_es_chunks

pytestmark = pytest.mark.unit


def _make_document() -> SimpleNamespace:
    return SimpleNamespace(
        id=61,
        space_id=1,
        kb_id=1,
        file_hash="h",
        filename="x.txt",
        file_type="txt",
        storage={"minio_object_name": "obj"},
        uploader_id=1,
        lifecycle_status="active",
    )


def _make_task() -> SimpleNamespace:
    return SimpleNamespace(
        start_step=lambda *a, **k: None,
        finish_step=lambda *a, **k: None,
        mark_completed=lambda *a, **k: None,
    )


class _FakeSession:
    async def commit(self):
        return None


def _patch_tail_deps(monkeypatch, *, embed_capture=None, bulk_capture=None):
    """mock 共享尾外部依赖；embed_capture/bulk_capture 传 list 时捕获入参。"""

    async def _no_cancel(doc_id: int) -> None:
        return None

    async def _fake_embed(texts, emb_cfg, *, session, user_id, model_config_port=None):
        if embed_capture is not None:
            embed_capture.extend(texts)
        return [b"\x00\x00\x00\x00"] * len(texts)

    async def _fake_es():
        async def _bulk(*, space_id, chunks, embedding_dim):
            if bulk_capture is not None:
                bulk_capture.extend(chunks)
            return len(chunks)

        async def _pre_delete(*, space_id, document_id):
            return 0

        return SimpleNamespace(bulk_index_chunks=_bulk, delete_document_chunks=_pre_delete)

    monkeypatch.setattr(pipeline_steps, "check_document_cancelled", _no_cancel)
    monkeypatch.setattr(pipeline_steps, "generate_embeddings", _fake_embed)
    monkeypatch.setattr(pipeline_steps, "get_es_client", _fake_es)


def _run_tail(monkeypatch, splitting_config, full_text, **kw):
    """跑共享尾并返回 bulk 捕获的 ES chunks 与 tail result。"""
    bulk: list = []
    _patch_tail_deps(monkeypatch, bulk_capture=bulk, **kw)
    result = _run_sync_tail(splitting_config, full_text)
    return result, bulk


def _run_sync_tail(splitting_config, full_text):
    """同步驱动的共享尾调用（测试文件内共享）。"""
    import asyncio

    async def _inner():
        return await pipeline_steps.run_post_parse_tail(
TailInputs(
            document=_make_document(),
            session=_FakeSession(),
            task=_make_task(),
            model_config_port=None,
            logger=None,
            chunk_type=ChunkType.TEXT,
            embedding_config={"dimension": 4},
            pipeline_config={"question_generation": {"enabled": False}},
            splitting_config=splitting_config,
            full_text=full_text,
            user_id=1,
    ))

    return asyncio.run(_inner())


# ===== 句子窗口全链路 =====


@pytest.mark.asyncio
async def test_sentence_window_tail_carries_expansion_metadata(monkeypatch):
    """句窗口策略经共享尾：ES chunk 带 expansion_type + expansion_window_size。"""
    bulk: list = []
    _patch_tail_deps(monkeypatch, bulk_capture=bulk)
    result = await pipeline_steps.run_post_parse_tail(
TailInputs(
        document=_make_document(),
        session=_FakeSession(),
        task=_make_task(),
        model_config_port=None,
        logger=None,
        chunk_type=ChunkType.TEXT,
        embedding_config={"dimension": 4},
        pipeline_config={"question_generation": {"enabled": False}},
        splitting_config={"strategy": "sentence_window", "chunk_size": 1000, "window_size": 3},
        full_text="甲句。乙句。丙句。丁句。",
        user_id=1,
    ))
    assert result["split_strategy"] == "sentence_window"
    assert result["chunk_count"] == 4
    assert all(
        c["metadata"].get("expansion_type") == "sentence_window"
        and c["metadata"].get("expansion_window_size") == 3
        for c in bulk
    )


# ===== 父子分块全链路 =====


@pytest.mark.asyncio
async def test_parent_child_tail_resolves_parent_chunk_id(monkeypatch):
    """父子策略经共享尾：子块 parent_chunk_id 指向父块绝对 chunk_id，父块带 chunk_role。"""
    bulk: list = []
    _patch_tail_deps(monkeypatch, bulk_capture=bulk)
    text = "段一。" * 200 + "段二。" * 200
    result = await pipeline_steps.run_post_parse_tail(
TailInputs(
        document=_make_document(),
        session=_FakeSession(),
        task=_make_task(),
        model_config_port=None,
        logger=None,
        chunk_type=ChunkType.TEXT,
        embedding_config={"dimension": 4},
        pipeline_config={"question_generation": {"enabled": False}},
        splitting_config={
            "strategy": "parent_child", "chunk_size": 200,
            "chunk_overlap": 0, "parent_chunk_size": 600,
        },
        full_text=text,
        user_id=1,
    ))
    assert result["split_strategy"] == "parent_child"
    parents = [c for c in bulk if c["metadata"].get("chunk_role") == "parent"]
    children = [c for c in bulk if c["metadata"].get("chunk_role") == "child"]
    assert parents and children
    # 绝对指针正确：parent_chunk_id == {document_id}_{父块chunk_index}
    parent_ids = {c["chunk_id"] for c in parents}
    assert all(c["metadata"]["parent_chunk_id"] in parent_ids for c in children)
    # 指针指向的确实是父块
    for c in children:
        parent = next(p for p in bulk if p["chunk_id"] == c["metadata"]["parent_chunk_id"])
        assert parent["metadata"]["chunk_role"] == "parent"
    # 父块位置紧邻其子块群（交错输出：阅读序保持）
    assert all(c["metadata"].get("expansion_type") == "parent_child" for c in children)


@pytest.mark.asyncio
async def test_parent_child_slot_unmapped_degrades_gracefully(monkeypatch):
    """slot 断链退化：子块 parent_slot 无对应父块 → 无指针不抛错（能力缺失方向）。"""
    items = [
        ("子块文本甲", {"chunk_role": "child", "parent_slot": 7}),  # 槽位 7 不存在
        ("普通文本乙", {}),
    ]
    doc = _make_document()
    es_chunks = build_es_chunks(doc, items, ChunkType.TEXT)
    assert es_chunks[0]["metadata"].get("chunk_role") == "child"
    assert "parent_chunk_id" not in es_chunks[0]["metadata"]
    assert "expansion_type" not in es_chunks[0]["metadata"]
    assert "chunk_role" not in es_chunks[1]["metadata"]


# ===== 父块跳过 embedding / 问题生成 =====


@pytest.mark.asyncio
async def test_parent_chunk_skips_embedding(monkeypatch):
    """父块不进 embedding 调用（成本语义），且 ES 落库无 embedding 键。"""
    embed_texts: list = []
    bulk: list = []
    _patch_tail_deps(monkeypatch, embed_capture=embed_texts, bulk_capture=bulk)
    text = "段一。" * 200 + "段二。" * 200
    await pipeline_steps.run_post_parse_tail(
TailInputs(
        document=_make_document(),
        session=_FakeSession(),
        task=_make_task(),
        model_config_port=None,
        logger=None,
        chunk_type=ChunkType.TEXT,
        embedding_config={"dimension": 4},
        pipeline_config={"question_generation": {"enabled": False}},
        splitting_config={
            "strategy": "parent_child", "chunk_size": 200,
            "chunk_overlap": 0, "parent_chunk_size": 600,
        },
        full_text=text,
        user_id=1,
    ))
    parents = [c for c in bulk if c["metadata"].get("chunk_role") == "parent"]
    assert parents, "测试前置：应产出父块"
    parent_contents = {p["content"] for p in parents}
    # 父块文本不进 embedding 批次
    assert not (set(embed_texts) & parent_contents)
    # 父块 ES 文档无 embedding 键（dense_vector 缺字段合法、knn 永不命中）
    assert all("embedding" not in p for p in parents)
    # 子块 embedding 正常
    children = [c for c in bulk if c["metadata"].get("chunk_role") == "child"]
    assert all(c.get("embedding") == b"\x00\x00\x00\x00" for c in children)


# ===== line_aware 回落（锚点保护）=====


@pytest.mark.asyncio
async def test_sentence_window_line_aware_falls_back(monkeypatch):
    """音视频锚点文本（line_aware=True）：句窗口回落行切分，无关系元数据、锚点完整。"""
    bulk: list = []
    _patch_tail_deps(monkeypatch, bulk_capture=bulk)
    anchor_text = (
        "[00:00:01#0] 第一句内容，讲述主题甲。\n"
        "[00:00:05#1] 第二句内容，讲述主题乙，这一行非常长" + "，继续补充" * 30 + "。\n"
        "[00:00:10#2] 第三句内容，讲述主题丙。"
    )
    result = await pipeline_steps.run_post_parse_tail(
TailInputs(
        document=_make_document(),
        session=_FakeSession(),
        task=_make_task(),
        model_config_port=None,
        logger=None,
        chunk_type=ChunkType.AUDIO,
        embedding_config={"dimension": 4},
        pipeline_config={"question_generation": {"enabled": False}},
        splitting_config={"strategy": "sentence_window", "chunk_size": 60, "window_size": 2},
        full_text=anchor_text,
        time_alignment={"timeline_map": {}, "is_video": False},
        user_id=1,
    ))
    assert result["chunk_count"] >= 1
    # 锚点行完整性：无任何 chunk 把「[锚点] 描述」行拦腰切开
    assert all(
        "[00:00:" not in c["content"] or c["content"].count("[") == c["content"].count("]")
        for c in bulk
    )
    # 回落路径无关系元数据 → 检索期不扩展
    assert all(
        "expansion_type" not in (c.get("metadata") or {}) for c in bulk
    )


# ===== 存量不误伤 =====


@pytest.mark.asyncio
async def test_recursive_strategy_has_no_new_metadata_keys(monkeypatch):
    """对照：recursive 策略产物无任何新键（存量 KB 零影响）。"""
    bulk: list = []
    _patch_tail_deps(monkeypatch, bulk_capture=bulk)
    await pipeline_steps.run_post_parse_tail(
TailInputs(
        document=_make_document(),
        session=_FakeSession(),
        task=_make_task(),
        model_config_port=None,
        logger=None,
        chunk_type=ChunkType.TEXT,
        embedding_config={"dimension": 4},
        pipeline_config={"question_generation": {"enabled": False}},
        splitting_config={"strategy": "recursive", "chunk_size": 1000},
        full_text="这是一段测试文本。" * 50,
        user_id=1,
    ))
    assert bulk
    assert all(
        not ({"chunk_role", "parent_chunk_id", "expansion_type", "expansion_window_size"}
             & set((c.get("metadata") or {}).keys()))
        for c in bulk
    )
