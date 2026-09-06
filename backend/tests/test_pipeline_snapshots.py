"""管道快照指纹计算测试。

验证指纹的稳定性（同输入同哈希）与隔离性（任一影响向量/切分/解析语义的
输入变化即失效，而不影响语义的输入（凭据等）不进入指纹）。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def _make_document(file_hash="abc123", file_type="PDF", doc_id=574):
    return SimpleNamespace(
        id=doc_id, file_hash=file_hash, file_type=file_type, storage={}
    )


# ---- canonical_sha256 稳定性 ----

def test_canonical_sha256_key_order_insensitive():
    """键顺序不同、分隔风格不同的同语义 payload 哈希一致。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        canonical_sha256,
    )

    a = canonical_sha256({"x": 1, "y": [1, 2], "z": {"k": "值"}})
    b = canonical_sha256({"z": {"k": "值"}, "y": [1, 2], "x": 1})
    assert a == b
    assert len(a) == 64


def test_canonical_sha256_handles_non_serializable():
    """不可 JSON 序列化对象（datetime 等）经 default=str 兜底不抛错。"""
    from datetime import datetime

    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        canonical_sha256,
    )

    h1 = canonical_sha256({"t": datetime(2026, 9, 4, 12, 0, 0)})
    h2 = canonical_sha256({"t": datetime(2026, 9, 4, 12, 0, 0)})
    assert h1 == h2


# ---- parse 指纹 ----

def test_parse_fingerprint_stable_for_same_inputs():
    """同文档同解析配置 → 指纹稳定。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_parse_fingerprint,
    )

    doc = _make_document()
    cfg = {"strategy": "deepdoc", "deepdoc_pdf_mode": "full"}
    fp1 = compute_parse_fingerprint(doc, cfg)
    fp2 = compute_parse_fingerprint(doc, cfg)
    assert fp1 == fp2
    assert len(fp1) == 64


def test_parse_fingerprint_changes_on_config_change():
    """解析配置任一变化 → 指纹失效。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_parse_fingerprint,
    )

    doc = _make_document()
    fp1 = compute_parse_fingerprint(doc, {"strategy": "deepdoc", "deepdoc_pdf_mode": "full"})
    fp2 = compute_parse_fingerprint(doc, {"strategy": "deepdoc", "deepdoc_pdf_mode": "plain"})
    assert fp1 != fp2


def test_parse_fingerprint_changes_on_file_change():
    """文件内容哈希变化 → 指纹失效。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_parse_fingerprint,
    )

    cfg = {"strategy": "default"}
    fp1 = compute_parse_fingerprint(_make_document(file_hash="h1"), cfg)
    fp2 = compute_parse_fingerprint(_make_document(file_hash="h2"), cfg)
    assert fp1 != fp2


def test_parse_fingerprint_file_type_case_insensitive():
    """file_type 大小写不敏感（PDF 与 pdf 同指纹，复用不受大小写影响）。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_parse_fingerprint,
    )

    cfg = {"strategy": "default"}
    fp1 = compute_parse_fingerprint(_make_document(file_type="PDF"), cfg)
    fp2 = compute_parse_fingerprint(_make_document(file_type="pdf"), cfg)
    assert fp1 == fp2


# ---- split 指纹 ----

def test_split_fingerprint_inherits_parse_change():
    """parse 指纹进入 split 指纹：parse 失效自动级联 split 失效。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_split_fingerprint,
    )

    cfg = {"strategy": "recursive", "chunk_size": 1000}
    fp_a = compute_split_fingerprint("parse-fp-a", "structural", cfg)
    fp_b = compute_split_fingerprint("parse-fp-b", "structural", cfg)
    assert fp_a != fp_b


def test_split_fingerprint_changes_on_splitting_config_change():
    """切分配置（strategy/chunk_size/overlap）变化 → split 指纹失效。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_split_fingerprint,
    )

    fp1 = compute_split_fingerprint("p", "structural", {"strategy": "recursive", "chunk_size": 1000})
    fp2 = compute_split_fingerprint("p", "structural", {"strategy": "recursive", "chunk_size": 500})
    fp3 = compute_split_fingerprint("p", "markdown", {"strategy": "recursive", "chunk_size": 1000})
    assert fp1 != fp2
    assert fp1 != fp3


# ---- embed 指纹 ----

def test_embed_fingerprint_inherits_split_change():
    """split 指纹进入 embed 指纹：split 失效自动级联 embed 失效。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_embed_fingerprint,
    )

    cfg = {"model": "text-embedding-v3", "dimension": 1024}
    assert compute_embed_fingerprint("split-fp-a", cfg) != compute_embed_fingerprint("split-fp-b", cfg)


def test_embed_fingerprint_changes_on_model_or_dimension_change():
    """模型/维度变化 → embed 指纹失效。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_embed_fingerprint,
    )

    fp1 = compute_embed_fingerprint("s", {"model": "m1", "dimension": 1024})
    fp2 = compute_embed_fingerprint("s", {"model": "m2", "dimension": 1024})
    fp3 = compute_embed_fingerprint("s", {"model": "m1", "dimension": 768})
    assert fp1 != fp2
    assert fp1 != fp3


def test_embed_fingerprint_ignores_credentials():
    """api_key/base_url 等连接凭据不影响 embed 指纹（凭据轮换不使向量失效）。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_embed_fingerprint,
    )

    cfg1 = {"model": "m", "dimension": 1024, "api_key": "key-a", "base_url": "https://a.example.com"}
    cfg2 = {"model": "m", "dimension": 1024, "api_key": "key-b", "base_url": "https://b.example.com"}
    assert compute_embed_fingerprint("s", cfg1) == compute_embed_fingerprint("s", cfg2)


def test_embed_fingerprint_includes_client_signature():
    """客户端实现签名进入指纹：签名 bump → 旧向量快照全部失效。"""
    import novamind.features.knowledge_space.services.pipeline_snapshots as ps

    cfg = {"model": "m", "dimension": 1024}
    fp_before = ps.compute_embed_fingerprint("s", cfg)
    old = ps.EMBEDDING_CLIENT_SIGNATURE
    try:
        ps.EMBEDDING_CLIENT_SIGNATURE = old + "-bumped"
        fp_after = ps.compute_embed_fingerprint("s", cfg)
    finally:
        ps.EMBEDDING_CLIENT_SIGNATURE = old
    assert fp_before != fp_after


# ---- snapshot_fingerprint getter ----

def test_snapshot_fingerprint_getter_reads_storage():
    """从 document.storage["pipeline_snapshots"] 读取已记录指纹。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        snapshot_fingerprint,
    )

    doc = _make_document()
    assert snapshot_fingerprint(doc, "parse") == ""
    assert snapshot_fingerprint(doc, "split") == ""

    doc.storage = {
        "pipeline_snapshots": {
            "parse_fingerprint": "p-fp",
            "split_fingerprint": "s-fp",
        }
    }
    assert snapshot_fingerprint(doc, "parse") == "p-fp"
    assert snapshot_fingerprint(doc, "split") == "s-fp"
    assert snapshot_fingerprint(doc, "embed") == ""


def test_snapshot_fingerprint_unknown_level_returns_empty():
    """未知层级返回空串而非抛错。"""
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        snapshot_fingerprint,
    )

    doc = _make_document()
    doc.storage = {"pipeline_snapshots": {"parse_fingerprint": "p-fp"}}
    assert snapshot_fingerprint(doc, "bogus") == ""
