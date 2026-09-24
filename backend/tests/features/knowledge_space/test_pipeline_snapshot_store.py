"""管道快照存取测试：save 序列 / load 降级 fail-open / invalidate 级联。

全部使用 mock MinIO 客户端与 mock AsyncSession，不触真实 MinIO/DB。
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


class FakeMinioClient:
    """内存版 MinIO 客户端：记录 upload/delete 调用，可选注入下载失败。"""

    def __init__(self, fail_download: bool = False):
        self.default_bucket = "knowledge-base"
        self.objects: dict = {}
        self.fail_download = fail_download
        self.uploaded: list = []
        self.deleted: list = []

    async def upload_file(self, object_name, file_data, content_type):
        self.objects[object_name] = file_data
        self.uploaded.append(object_name)

    async def download_document(self, bucket_name, object_name):
        if self.fail_download or object_name not in self.objects:
            raise RuntimeError(f"s3 error: no such object {object_name}")
        return self.objects[object_name]

    async def delete_document(self, bucket_name, object_name):
        self.deleted.append(object_name)
        self.objects.pop(object_name, None)
        return True

    async def get_file_url(self, bucket_name, object_name, expires=3600):
        return f"https://minio.test/{bucket_name}/{object_name}?sig=fresh"


class FakeSession:
    """记录 commit 次数的假 AsyncSession。"""

    def __init__(self):
        self.commit_count = 0

    async def commit(self):
        self.commit_count += 1


def _make_document(doc_id=574, storage=None):
    if storage is None:
        storage = {
            "minio_bucket": "knowledge-base",
            "minio_object_name": f"spaces/1/kb/2/docs/{doc_id}/report.pdf",
        }
    return SimpleNamespace(
        id=doc_id,
        file_hash="abc123",
        file_type="pdf",
        storage=storage,
        get_minio_bucket=lambda: storage.get("minio_bucket"),
    )


def _logger():
    from novamind.shared.logging import get_logger

    return get_logger(__name__)


# ---- save_parse_snapshot ----

def test_save_parse_snapshot_uploads_and_commits():
    """保存解析快照：上传 JSON → storage 写指纹+对象名指针 → commit。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        SNAPSHOT_STORAGE_KEY,
        build_parse_snapshot_payload,
        parse_meta_object_name,
        save_parse_snapshot,
    )

    doc = _make_document()
    minio = FakeMinioClient()
    session = FakeSession()
    payload = build_parse_snapshot_payload(
        parse_fingerprint="p-fp",
        full_text="全文内容",
        parse_metadata={"parser": "DeepDocParser"},
        prechunked_items=[("块1", {"pages": [1]}), ("块2", {})],
    )

    ok = asyncio.run(save_parse_snapshot(
        doc, session, _logger(),
        minio_client=minio, parse_fingerprint="p-fp", payload=payload,
    ))

    assert ok is True
    obj = parse_meta_object_name(doc)
    assert obj in minio.objects
    stored = json.loads(minio.objects[obj].decode("utf-8"))
    assert stored["parse_fingerprint"] == "p-fp"
    assert stored["full_text"] == "全文内容"
    assert stored["prechunked_items"] == [["块1", {"pages": [1]}], ["块2", {}]]
    state = doc.storage[SNAPSHOT_STORAGE_KEY]
    assert state["parse_fingerprint"] == "p-fp"
    assert state["parse_meta_object"] == obj
    assert session.commit_count == 1


def test_save_parse_snapshot_failure_is_fail_open():
    """上传失败 → 返回 False，storage 不写指针，不抛错。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        build_parse_snapshot_payload,
        save_parse_snapshot,
    )

    doc = _make_document()
    minio = FakeMinioClient()

    async def broken_upload(*args, **kwargs):
        raise RuntimeError("minio down")

    minio.upload_file = broken_upload
    session = FakeSession()
    payload = build_parse_snapshot_payload(parse_fingerprint="p", full_text="x")

    ok = asyncio.run(save_parse_snapshot(
        doc, session, _logger(),
        minio_client=minio, parse_fingerprint="p", payload=payload,
    ))

    assert ok is False
    assert "pipeline_snapshots" not in (doc.storage or {})
    assert session.commit_count == 0


def test_build_parse_snapshot_payload_includes_media_fields():
    """time_alignment / frame_paths 进入 payload，frame_paths int 键转 str。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        build_parse_snapshot_payload,
    )

    payload = build_parse_snapshot_payload(
        parse_fingerprint="p",
        full_text="文本",
        time_alignment={"timeline_map": {}, "is_video": True},
        frame_paths={0: "frames/f0.png", 3: "frames/f3.png"},
    )
    assert payload["time_alignment"] == {"timeline_map": {}, "is_video": True}
    assert payload["frame_paths"] == {"0": "frames/f0.png", "3": "frames/f3.png"}


# ---- save_split_snapshot ----

def test_save_split_snapshot_roundtrip_and_alignment_flag():
    """切分快照保存→读取往返一致，alignment_applied 标记透传。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        load_split_snapshot,
        save_split_snapshot,
    )

    doc = _make_document()
    minio = FakeMinioClient()
    session = FakeSession()
    items = [("块1", {"pages": [1, 2]}), ("块2", {"entry_kinds": ["text"]})]

    asyncio.run(save_split_snapshot(
        doc, session, _logger(),
        minio_client=minio, split_fingerprint="s-fp",
        chunk_items=items, alignment_applied=True,
    ))

    loaded = asyncio.run(load_split_snapshot(doc, minio, _logger()))
    assert loaded is not None
    assert loaded["split_fingerprint"] == "s-fp"
    assert loaded["alignment_applied"] is True
    assert loaded["chunk_items"] == [("块1", {"pages": [1, 2]}), ("块2", {"entry_kinds": ["text"]})]


# ---- save_embeddings_snapshot ----

def test_save_embeddings_snapshot_roundtrip_and_rounding():
    """向量快照往返一致；向量按 6 位小数降精度；None 向量保留。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        load_embeddings_snapshot,
        save_embeddings_snapshot,
    )

    doc = _make_document()
    minio = FakeMinioClient()
    session = FakeSession()
    embeddings = [[0.123456789, 1 / 3], None, [-0.5]]

    asyncio.run(save_embeddings_snapshot(
        doc, session, _logger(),
        minio_client=minio, embed_fingerprint="e-fp",
        embeddings=embeddings, embedding_model="text-embedding-v3",
    ))

    loaded = asyncio.run(load_embeddings_snapshot(doc, minio, _logger()))
    assert loaded is not None
    assert loaded["embed_fingerprint"] == "e-fp"
    assert loaded["embedding_model"] == "text-embedding-v3"
    assert loaded["embeddings"][0] == [0.123457, 0.333333]
    assert loaded["embeddings"][1] is None
    assert loaded["embeddings"][2] == [-0.5]


def test_save_embeddings_snapshot_records_model_in_state():
    """embedding_model 同时写进 storage 指针，便于详情页展示。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        SNAPSHOT_STORAGE_KEY,
        save_embeddings_snapshot,
    )

    doc = _make_document()
    minio = FakeMinioClient()
    session = FakeSession()

    asyncio.run(save_embeddings_snapshot(
        doc, session, _logger(),
        minio_client=minio, embed_fingerprint="e-fp",
        embeddings=[[0.1]], embedding_model="qwen3-emb",
    ))

    assert doc.storage[SNAPSHOT_STORAGE_KEY]["embedding_model"] == "qwen3-emb"
    assert doc.storage[SNAPSHOT_STORAGE_KEY]["embed_fingerprint"] == "e-fp"


# ---- load 降级（fail-open）----

def test_load_missing_pointer_returns_none():
    """storage 无指针（旧文档/未存过快照）→ None，不触发下载。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        load_embeddings_snapshot,
        load_parse_snapshot,
        load_split_snapshot,
    )

    doc = _make_document(storage={"minio_bucket": "knowledge-base", "minio_object_name": "x/y.pdf"})
    minio = FakeMinioClient()

    assert asyncio.run(load_parse_snapshot(doc, minio, _logger())) is None
    assert asyncio.run(load_split_snapshot(doc, minio, _logger())) is None
    assert asyncio.run(load_embeddings_snapshot(doc, minio, _logger())) is None
    assert minio.uploaded == [] and minio.deleted == []


def test_load_download_failure_returns_none():
    """MinIO 对象缺失/下载失败 → warning + None（fail-open，绝不抛错）。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        load_embeddings_snapshot,
        load_parse_snapshot,
        load_split_snapshot,
    )

    doc = _make_document(storage={
        "minio_bucket": "knowledge-base",
        "minio_object_name": "x/y.pdf",
        "pipeline_snapshots": {
            "parse_meta_object": "x/y_parsed/parse_meta.json",
            "chunks_object": "x/y_artifacts/chunks.json",
            "embeddings_object": "x/y_artifacts/embeddings.json",
        },
    })
    minio = FakeMinioClient(fail_download=True)

    assert asyncio.run(load_parse_snapshot(doc, minio, _logger())) is None
    assert asyncio.run(load_split_snapshot(doc, minio, _logger())) is None
    assert asyncio.run(load_embeddings_snapshot(doc, minio, _logger())) is None


def test_load_corrupt_json_returns_none():
    """MinIO 上坏 JSON → None 而非抛错。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        load_parse_snapshot,
    )

    doc = _make_document(storage={
        "minio_bucket": "knowledge-base",
        "minio_object_name": "x/y.pdf",
        "pipeline_snapshots": {"parse_meta_object": "x/y_parsed/parse_meta.json"},
    })
    minio = FakeMinioClient()
    minio.objects["x/y_parsed/parse_meta.json"] = b"{not valid json"

    assert asyncio.run(load_parse_snapshot(doc, minio, _logger())) is None


def test_load_split_snapshot_bad_shape_returns_none():
    """切分快照缺 chunk_items（结构异常）→ None。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        load_split_snapshot,
    )

    doc = _make_document(storage={
        "minio_bucket": "knowledge-base",
        "minio_object_name": "x/y.pdf",
        "pipeline_snapshots": {"chunks_object": "x/y_artifacts/chunks.json"},
    })
    minio = FakeMinioClient()
    minio.objects["x/y_artifacts/chunks.json"] = json.dumps({"split_fingerprint": "s"}).encode()

    assert asyncio.run(load_split_snapshot(doc, minio, _logger())) is None


# ---- invalidate 级联 ----

def _doc_with_all_snapshots(doc_id=574):
    doc = _make_document(doc_id=doc_id)
    doc.storage = {
        "minio_bucket": "knowledge-base",
        "minio_object_name": f"spaces/1/kb/2/docs/{doc_id}/report.pdf",
        "pipeline_snapshots": {
            "version": 1,
            "parse_fingerprint": "p-fp",
            "parse_meta_object": f"spaces/1/kb/2/docs/{doc_id}/report.pdf_parsed/parse_meta.json",
            "split_fingerprint": "s-fp",
            "chunks_object": f"spaces/1/kb/2/docs/{doc_id}/report.pdf_artifacts/chunks.json",
            "embed_fingerprint": "e-fp",
            "embeddings_object": f"spaces/1/kb/2/docs/{doc_id}/report.pdf_artifacts/embeddings.json",
            "embedding_model": "m",
        },
    }
    return doc


def test_invalidate_parse_cascades_all_levels():
    """parse 级失效：删 3 个对象 + 清空全部快照状态。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        SNAPSHOT_STORAGE_KEY,
        invalidate_snapshots_from,
    )

    doc = _doc_with_all_snapshots()
    minio = FakeMinioClient()
    session = FakeSession()

    asyncio.run(invalidate_snapshots_from(doc, minio, session, _logger(), level="parse"))

    assert len(minio.deleted) == 3
    assert SNAPSHOT_STORAGE_KEY not in doc.storage
    assert session.commit_count == 1


def test_invalidate_split_cascades_downstream_only():
    """split 级失效：删 chunks+embeddings，保留 parse 指纹。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        SNAPSHOT_STORAGE_KEY,
        invalidate_snapshots_from,
    )

    doc = _doc_with_all_snapshots()
    minio = FakeMinioClient()
    session = FakeSession()

    asyncio.run(invalidate_snapshots_from(doc, minio, session, _logger(), level="split"))

    assert len(minio.deleted) == 2
    state = doc.storage[SNAPSHOT_STORAGE_KEY]
    assert state["parse_fingerprint"] == "p-fp"
    assert state["parse_meta_object"].endswith("parse_meta.json")
    assert "split_fingerprint" not in state
    assert "chunks_object" not in state
    assert "embed_fingerprint" not in state
    assert "embeddings_object" not in state


def test_invalidate_embed_only_removes_embeddings():
    """embed 级失效：只删 embeddings 对象，parse/split 指纹保留。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        SNAPSHOT_STORAGE_KEY,
        invalidate_snapshots_from,
    )

    doc = _doc_with_all_snapshots()
    minio = FakeMinioClient()
    session = FakeSession()

    asyncio.run(invalidate_snapshots_from(doc, minio, session, _logger(), level="embed"))

    assert minio.deleted == [
        "spaces/1/kb/2/docs/574/report.pdf_artifacts/embeddings.json"
    ]
    state = doc.storage[SNAPSHOT_STORAGE_KEY]
    assert state["parse_fingerprint"] == "p-fp"
    assert state["split_fingerprint"] == "s-fp"
    assert "embed_fingerprint" not in state


def test_invalidate_with_no_snapshots_is_noop():
    """无快照的文档失效 → 无删除、不抛错。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        invalidate_snapshots_from,
    )

    doc = _make_document()
    minio = FakeMinioClient()
    session = FakeSession()

    asyncio.run(invalidate_snapshots_from(doc, minio, session, _logger(), level="parse"))

    assert minio.deleted == []
    assert "pipeline_snapshots" not in doc.storage


def test_invalidate_delete_failure_is_fail_open():
    """MinIO 删除失败 → 不抛错，storage 指针照常剪掉（指纹比对才是复用判据）。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        SNAPSHOT_STORAGE_KEY,
        invalidate_snapshots_from,
    )

    doc = _doc_with_all_snapshots()
    minio = FakeMinioClient()

    async def broken_delete(*args, **kwargs):
        raise RuntimeError("minio down")

    minio.delete_document = broken_delete
    session = FakeSession()

    asyncio.run(invalidate_snapshots_from(doc, minio, session, _logger(), level="embed"))

    assert SNAPSHOT_STORAGE_KEY in doc.storage
    assert "embed_fingerprint" not in doc.storage[SNAPSHOT_STORAGE_KEY]


# ---- figure 短路径兜底 ----

def test_resolve_figure_short_paths_updates_regions():
    """按 minio_object_name 的 basename 补算短文件名：region 原地更新 + 返回映射。
    旧存量快照（image_url 是过期预签名 URL）的 resume 兜底路径。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        resolve_figure_short_paths,
    )

    payload = {
        "parse_metadata": {
            "figure_regions": [
                {"artifact_id": "fig-1", "minio_object_name": "x_figures/figure_fig_1_3.png",
                 "image_url": "https://old/expired"},
                {"artifact_id": "fig-2", "minio_object_name": "x_figures/figure_fig_2_5.png",
                 "image_url": "https://old/expired-2"},
            ]
        }
    }

    url_map = resolve_figure_short_paths(payload, _logger())

    assert url_map == {
        "fig-1": "figure_fig_1_3.png",
        "fig-2": "figure_fig_2_5.png",
    }
    regions = payload["parse_metadata"]["figure_regions"]
    assert regions[0]["image_url"] == "figure_fig_1_3.png"
    assert regions[1]["image_url"] == "figure_fig_2_5.png"


def test_resolve_figure_short_paths_new_snapshot_noop():
    """新快照 image_url 已是短文件名 → 映射仍返回（幂等），region 不变。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        resolve_figure_short_paths,
    )

    payload = {
        "parse_metadata": {
            "figure_regions": [
                {"artifact_id": "fig-1", "minio_object_name": "x_figures/figure_fig_1_3.png",
                 "image_url": "figure_fig_1_3.png"},
            ]
        }
    }

    url_map = resolve_figure_short_paths(payload, _logger())

    assert url_map == {"fig-1": "figure_fig_1_3.png"}
    assert payload["parse_metadata"]["figure_regions"][0]["image_url"] == "figure_fig_1_3.png"


def test_resolve_figure_short_paths_no_regions_returns_empty():
    """无 figure_regions → 空映射。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        resolve_figure_short_paths,
    )

    assert resolve_figure_short_paths({"parse_metadata": {}}, _logger()) == {}


def test_resolve_figure_short_paths_skips_regions_without_object_name():
    """缺 minio_object_name 或 artifact_id 的 region 跳过（更旧的快照形态）。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        resolve_figure_short_paths,
    )

    payload = {
        "parse_metadata": {
            "figure_regions": [
                {"artifact_id": "no-obj", "image_url": "https://old/expired"},
                {"minio_object_name": "x_figures/figure_ok_1.png"},
                {"artifact_id": "ok", "minio_object_name": "x_figures/figure_ok_1.png",
                 "image_url": "https://old/ok"},
            ]
        }
    }

    url_map = resolve_figure_short_paths(payload, _logger())

    assert url_map == {"ok": "figure_ok_1.png"}


# ---- restore_frame_paths ----

def test_restore_frame_paths_converts_str_keys():
    """JSON str 键还原为 int 键；坏键跳过。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        restore_frame_paths,
    )

    result = restore_frame_paths({"0": "a.png", "12": "b.png", "bad": "c.png"})
    assert result == {0: "a.png", 12: "b.png"}
    assert restore_frame_paths(None) == {}
