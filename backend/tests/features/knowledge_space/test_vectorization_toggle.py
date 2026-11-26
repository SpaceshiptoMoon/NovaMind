"""向量化开关回归测试（2026-11-26 向量化节点）。

vectorization.enabled=False 时：embedded 节点跳过向量计算——chunks 照常入 ES
但不带 dense 向量（父块先例证明缺向量字段合法，BM25 检索不受影响），语义检索
对该文档不可召回。开→关不清理存量向量；关→开经嵌入快照指纹自动补嵌。

正例：默认（无配置）照常向量化；关闭态 ES chunks 无 embedding 字段。
反例保护：关闭态不调用 embedding 服务（省配额），开关对切分无影响。
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

from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    KnowledgeBaseConfig,
    VectorizationConfig,
)
from novamind.features.knowledge_space.services import pipeline_steps
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.services.pipeline_steps import TailInputs

pytestmark = pytest.mark.unit

_TEST_LOGGER = get_logger("test.vectorization")


def _make_document() -> SimpleNamespace:
    return SimpleNamespace(
        id=71,
        space_id=1,
        kb_id=1,
        file_hash="h",
        filename="doc.md",
        file_type="md",
        storage={"minio_object_name": "obj"},
        uploader_id=1,
    )


def _make_task() -> SimpleNamespace:
    finish_metrics: dict[str, Any] = {}

    def _finish(name, metrics=None, *a, **k):
        finish_metrics[name] = metrics or {}

    return SimpleNamespace(
        start_step=lambda *a, **k: None,
        finish_step=_finish,
        mark_completed=lambda *a, **k: None,
        _finish_metrics=finish_metrics,
    )


class _FakeSession:
    async def commit(self):
        return None


def _patch_tail_deps(monkeypatch):
    """mock 共享尾外部依赖；embedding 调用计数与 ES chunks 落库捕获。"""
    state: dict = {"embed_calls": 0, "es_chunks": []}

    async def _no_cancel(doc_id: int) -> None:
        return None

    async def _fake_embed(texts, emb_cfg, *, session, user_id, model_config_port=None):
        state["embed_calls"] += len(texts)
        return [[float(len(texts))] * 4] * len(texts)

    async def _fake_es():
        async def _bulk(*, space_id, chunks, embedding_dim):
            state["es_chunks"] = list(chunks)
            return len(chunks)

        async def _pre_delete(*, space_id, document_id):
            return 0

        return SimpleNamespace(bulk_index_chunks=_bulk, delete_document_chunks=_pre_delete)

    monkeypatch.setattr(pipeline_steps, "check_document_cancelled", _no_cancel)
    monkeypatch.setattr(pipeline_steps, "generate_embeddings", _fake_embed)
    monkeypatch.setattr(pipeline_steps, "get_es_client", _fake_es)
    return state


async def _run_tail(pipeline_config: dict) -> dict:
    return await pipeline_steps.run_post_parse_tail(
        TailInputs(
            document=_make_document(),
            session=_FakeSession(),
            task=_make_task(),
            model_config_port=None,
            logger=_TEST_LOGGER,
            chunk_type=ChunkType.TEXT,
            embedding_config={"dimension": 4},
            pipeline_config=pipeline_config,
            splitting_config={"strategy": "recursive", "chunk_size": 200},
            full_text="向量开关回归测试。" * 80,
            user_id=1,
        )
    )


class TestVectorizationGate:
    @pytest.mark.asyncio
    async def test_disabled_skips_embedding_and_indexes_plain_chunks(self, monkeypatch):
        """关闭向量化：embedding 服务零调用，ES chunks 无向量字段，索引照常。"""
        state = _patch_tail_deps(monkeypatch)
        result = await _run_tail({"vectorization": {"enabled": False}})

        assert state["embed_calls"] == 0, "关闭态不得调用 embedding 服务"
        assert result["chunk_count"] >= 1
        assert state["es_chunks"], "chunks 应照常入 ES"
        assert all("embedding" not in c for c in state["es_chunks"]), "ES chunks 不应带向量"

    @pytest.mark.asyncio
    async def test_default_enabled_computes_embeddings(self, monkeypatch):
        """默认（无 vectorization 配置）：照常向量化，ES chunks 带向量。"""
        state = _patch_tail_deps(monkeypatch)
        result = await _run_tail({})

        assert state["embed_calls"] > 0, "默认应调用 embedding 服务"
        assert result["chunk_count"] >= 1
        assert all(c.get("embedding") for c in state["es_chunks"]), "ES chunks 应带向量"

    @pytest.mark.asyncio
    async def test_disabled_does_not_affect_split(self, monkeypatch):
        """开关只影响向量计算，切分行为不受影响。"""
        state = _patch_tail_deps(monkeypatch)
        result_off = await _run_tail({"vectorization": {"enabled": False}})
        state2 = _patch_tail_deps(monkeypatch)
        result_on = await _run_tail({})
        assert result_off["split_strategy"] == result_on["split_strategy"]
        assert result_off["chunk_count"] == result_on["chunk_count"]


class TestSchema:
    def test_default_enabled(self):
        assert KnowledgeBaseConfig().vectorization.enabled is True

    def test_explicit_disabled(self):
        cfg = KnowledgeBaseConfig.model_validate({"vectorization": {"enabled": False}})
        assert cfg.vectorization.enabled is False

    def test_config_update_roundtrip(self):
        cfg = KnowledgeBaseConfig.model_validate({"vectorization": {"enabled": False}})
        dumped = cfg.model_dump()
        assert dumped["vectorization"]["enabled"] is False
        reparsed = KnowledgeBaseConfig.model_validate(dumped)
        assert reparsed.vectorization.enabled is False
