"""管道断点续跑接入测试：_run_post_parse_tail 的 split/embed 快照命中与回写。

monkeypatch 内部依赖（切分/嵌入/ES/取消检查/ClientFactory），真实执行 _run_post_parse_tail：
- 快照命中 → 跳过切分/embedding 调用 + metrics 带 resumed 标记
- 指纹失效（storage 指纹 ≠ 当前指纹）→ 重做并写回快照
- parse_fingerprint=None → 完全不启用快照（兼容既有行为）
- 快照对象损坏/缺失 → fail-open 重做
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


class FakeMinio:
    """内存 MinIO。"""

    def __init__(self):
        self.default_bucket = "knowledge-base"
        self.objects = {}

    async def upload_file(self, object_name, data, content_type):
        self.objects[object_name] = data

    async def download_document(self, bucket_name, object_name):
        if object_name not in self.objects:
            raise RuntimeError("no such object")
        return self.objects[object_name]

    async def delete_document(self, bucket_name, object_name):
        self.objects.pop(object_name, None)
        return True


class FakeSession:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


class FakeTask:
    """最小 DocumentTask 替身：维护 step_progress + 节点方法。"""

    def __init__(self):
        self.step_progress = {}
        self.pipeline_result = {}

    def start_step(self, name):
        self.step_progress[name] = {"status": "running", "metrics": {}}

    def finish_step(self, name, metrics=None):
        node = self.step_progress.get(name) or {}
        node.update({"status": "done", "metrics": metrics or {}})
        self.step_progress[name] = node

    def mark_completed(self, result=None):
        if result:
            self.pipeline_result.update(result)


def _make_document(storage=None):
    if storage is None:
        storage = {
            "minio_bucket": "knowledge-base",
            "minio_object_name": "spaces/1/kb/2/docs/9/doc.pdf",
        }
    return SimpleNamespace(
        id=9, file_hash="hash9", file_type="pdf", uploader_id=7,
        space_id=1, kb_id=2, filename="doc.pdf", storage=storage,
        get_minio_bucket=lambda: storage.get("minio_bucket"),
    )


def _logger():
    from novamind.shared.logging import get_logger

    return get_logger(__name__)


def _run_tail_coro(document, task, session, *, parse_fp, minio,
                   split_calls, embed_calls, splitting_config=None):
    """构造 tail 协程：全部外部依赖已由调用方的 with 块 patch。"""
    from novamind.features.knowledge_space.schemas.enums import ChunkType
    from novamind.features.knowledge_space.services import document_pipeline as dp

    async def fake_split(*args, **kwargs):
        split_calls.append(1)
        return [("块一", {}), ("块二", {}), ("块三", {})]

    def fake_embeddings(texts, cfg, **kwargs):
        embed_calls.append(len(texts))
        return [[0.1, 0.2] for _ in texts]

    return dp._run_post_parse_tail(
        document=document, session=session, task=task,
        model_config_port=MagicMock(), logger=_logger(),
        chunk_type=ChunkType.TEXT,
        embedding_config={"model": "emb-1", "dimension": 1024, "batch_size": 32},
        pipeline_config={"question_generation": {"enabled": False}},
        splitting_config=splitting_config or {"strategy": "recursive", "chunk_size": 1000},
        full_text="全文内容" * 50,
        parse_fingerprint=parse_fp,
        user_id=7,
    ), fake_split, fake_embeddings


class _FakeCF:
    """patch 目标：tail 内 `from ...client_factory import ClientFactory` 取此类。"""

    minio = None

    @classmethod
    async def get_minio_client(cls):
        return cls.minio


def _tail_patches(minio, split_mock, embed_mock):
    """tail 全部外部依赖的 patch 集合。"""
    es_client = MagicMock()
    es_client.bulk_index_chunks = AsyncMock(return_value=3)
    return [
        patch(
            "novamind.shared.storage.client_factory.ClientFactory", _FakeCF,
        ),
        patch(
            "novamind.features.knowledge_space.services.document_pipeline._check_document_cancelled",
            AsyncMock(return_value=None),
        ),
        patch(
            "novamind.features.knowledge_space.services.document_pipeline._get_es_client_static",
            AsyncMock(return_value=es_client),
        ),
        patch(
            "novamind.features.knowledge_space.services.document_pipeline._generate_embeddings_static",
            embed_mock,
        ),
        patch(
            "novamind.features.knowledge_space.services.media_processing._split_md_text",
            split_mock,
        ),
        patch(
            "novamind.features.knowledge_space.services.media_processing.maybe_semantic_embedding_client",
            AsyncMock(return_value=None),
        ),
    ], es_client


PARSE_FP_A = "a" * 64
PARSE_FP_B = "b" * 64


def _state(doc):
    return doc.storage.get("pipeline_snapshots") or {}


def _do_run(document, task, session, *, parse_fp, minio,
            splitting_config=None, es_indexed=3):
    """受控依赖下执行 tail，返回 (result, split_calls, embed_calls, es_client)。"""
    from novamind.features.knowledge_space.services import document_pipeline as dp

    split_calls, embed_calls = [], []

    async def fake_split(*args, **kwargs):
        split_calls.append(1)
        return [("块一", {}), ("块二", {}), ("块三", {})]

    def fake_embeddings(texts, cfg, **kwargs):
        embed_calls.append(len(texts))
        return [[0.1, 0.2] for _ in texts]

    es_client = MagicMock()
    es_client.bulk_index_chunks = AsyncMock(return_value=es_indexed)

    _FakeCF.minio = minio

    from novamind.features.knowledge_space.schemas.enums import ChunkType

    with patch("novamind.shared.storage.client_factory.ClientFactory", _FakeCF), \
         patch.object(dp, "_check_document_cancelled", AsyncMock(return_value=None)), \
         patch.object(dp, "_get_es_client_static", AsyncMock(return_value=es_client)), \
         patch.object(dp, "_generate_embeddings_static", AsyncMock(side_effect=fake_embeddings)), \
         patch(
             "novamind.features.knowledge_space.services.media_processing._split_md_text",
             AsyncMock(side_effect=fake_split),
         ), patch(
             "novamind.features.knowledge_space.services.media_processing.maybe_semantic_embedding_client",
             AsyncMock(return_value=None),
         ):
        result = asyncio.run(dp._run_post_parse_tail(
            document=document, session=session, task=task,
            model_config_port=MagicMock(), logger=_logger(),
            chunk_type=ChunkType.TEXT,
            embedding_config={"model": "emb-1", "dimension": 1024, "batch_size": 32},
            pipeline_config={"question_generation": {"enabled": False}},
            splitting_config=splitting_config or {"strategy": "recursive", "chunk_size": 1000},
            full_text="全文内容" * 50,
            parse_fingerprint=parse_fp,
            user_id=7,
        ))
    return result, split_calls, embed_calls, es_client


# ---- 首跑：写回 split + embed 快照 ----

def test_first_run_writes_split_and_embed_snapshots():
    """parse_fp 启用时首跑：split 与 embed 快照均写入 storage，MinIO 有对象。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_embed_fingerprint,
        compute_split_fingerprint,
    )

    minio = FakeMinio()
    doc = _make_document()
    result, split_calls, embed_calls, _ = _do_run(
        doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio,
    )

    assert result["chunk_count"] == 3
    assert len(split_calls) == 1 and len(embed_calls) == 1
    state = _state(doc)
    expected_split_fp = compute_split_fingerprint(
        PARSE_FP_A, "recursive", {"strategy": "recursive", "chunk_size": 1000},
    )
    assert state["split_fingerprint"] == expected_split_fp
    assert state["chunks_object"].endswith("chunks.json")
    assert state["embed_fingerprint"] == compute_embed_fingerprint(
        expected_split_fp, {"model": "emb-1", "dimension": 1024, "batch_size": 32},
    )
    assert state["embeddings_object"].endswith("embeddings.json")
    assert any(k.endswith("chunks.json") for k in minio.objects)
    assert any(k.endswith("embeddings.json") for k in minio.objects)


def test_first_run_without_parse_fp_writes_nothing():
    """parse_fp=None（未启用）→ 不写任何快照、不触碰 MinIO（兼容既有调用）。"""
    minio = FakeMinio()
    doc = _make_document()

    result, split_calls, embed_calls, _ = _do_run(
        doc, FakeTask(), FakeSession(), parse_fp=None, minio=minio,
    )

    assert result["chunk_count"] == 3
    assert _state(doc) == {}
    assert minio.objects == {}


# ---- 二跑：split/embed 快照命中 ----

def test_second_run_resumes_split_and_embed():
    """同指纹二跑：切分与 embedding 调用均为 0 次。"""
    minio = FakeMinio()
    doc = _make_document()

    _do_run(doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio)

    result, split_calls, embed_calls, _ = _do_run(
        doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio,
    )

    assert split_calls == [], "split 快照命中不应再调切分"
    assert embed_calls == [], "embed 快照命中不应再调 embedding"
    assert result["chunk_count"] == 3


def test_resumed_metrics_flagged():
    """resume 命中时 split/embedded 节点 metrics 带 resumed=True。"""
    minio = FakeMinio()
    doc = _make_document()

    _do_run(doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio)

    resumed_task = FakeTask()
    _do_run(doc, resumed_task, FakeSession(), parse_fp=PARSE_FP_A, minio=minio)

    assert resumed_task.step_progress["split"]["metrics"].get("resumed") is True
    assert resumed_task.step_progress["embedded"]["metrics"].get("resumed") is True


# ---- 指纹失效 → 重做并覆盖快照 ----

def test_fingerprint_mismatch_redo_and_overwrite():
    """parse_fp 变化 → split 指纹级联失效 → 重做切分/嵌入，快照写新指纹。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_split_fingerprint,
    )

    minio = FakeMinio()
    doc = _make_document()
    _do_run(doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio)
    old_split_fp = _state(doc)["split_fingerprint"]

    result, split_calls, embed_calls, _ = _do_run(
        doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_B, minio=minio,
    )

    assert len(split_calls) == 1, "指纹失效应重做切分"
    assert len(embed_calls) == 1, "指纹失效应重做嵌入"
    new_split_fp = _state(doc)["split_fingerprint"]
    assert new_split_fp == compute_split_fingerprint(
        PARSE_FP_B, "recursive", {"strategy": "recursive", "chunk_size": 1000},
    )
    assert new_split_fp != old_split_fp


def test_splitting_config_change_redoes_split():
    """同一 parse_fp 下改切分配置 → split/embed 级联重做。"""
    minio = FakeMinio()
    doc = _make_document()
    _do_run(doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio)

    result, split_calls, embed_calls, _ = _do_run(
        doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio,
        splitting_config={"strategy": "recursive", "chunk_size": 500},
    )

    assert len(split_calls) == 1, "切分配置变化应重做切分"
    assert len(embed_calls) == 1


def test_snapshot_missing_degrades_to_full_rerun():
    """切分快照对象缺失 → 仅切分降级重做；向量快照完好仍复用（部分降级语义）。"""
    minio = FakeMinio()
    doc = _make_document()
    _do_run(doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio)

    # 指针指向不存在的对象（模拟 MinIO 对象被清）
    doc.storage["pipeline_snapshots"]["chunks_object"] = (
        "spaces/1/kb/2/docs/9/doc.pdf_artifacts/missing.json"
    )

    result, split_calls, embed_calls, _ = _do_run(
        doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio,
    )

    assert len(split_calls) == 1, "切分快照对象缺失应降级重做切分"
    assert embed_calls == [], "向量快照仍有效（embed_fp 未变）应复用，不重算"
    assert result["chunk_count"] == 3
    assert _state(doc)["chunks_object"].endswith("chunks.json")


def test_both_snapshots_missing_full_rerun():
    """两级快照对象全部缺失 → 切分与嵌入均降级重做，快照全部重写。"""
    minio = FakeMinio()
    doc = _make_document()
    _do_run(doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio)

    doc.storage["pipeline_snapshots"]["chunks_object"] = (
        "spaces/1/kb/2/docs/9/doc.pdf_artifacts/missing.json"
    )
    doc.storage["pipeline_snapshots"]["embeddings_object"] = (
        "spaces/1/kb/2/docs/9/doc.pdf_artifacts/missing_emb.json"
    )

    result, split_calls, embed_calls, _ = _do_run(
        doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio,
    )

    assert len(split_calls) == 1
    assert len(embed_calls) == 1
    assert result["chunk_count"] == 3


# ---- ES 索引仍每次执行（bulk 覆盖式幂等，无需快照）----

def test_es_index_always_runs_even_on_resume():
    """resume 命中时 ES bulk 索引仍执行（覆盖式幂等，是 indexed 节点的本体工作）。"""
    minio = FakeMinio()
    doc = _make_document()
    _do_run(doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio)

    result, _s, _e, es_client = _do_run(
        doc, FakeTask(), FakeSession(), parse_fp=PARSE_FP_A, minio=minio,
    )

    assert es_client.bulk_index_chunks.await_count == 1
    assert result["indexed_count"] == 3
