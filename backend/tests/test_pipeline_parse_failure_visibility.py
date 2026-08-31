"""解析管道静默失败修复回归测试（P0 + P1）。

覆盖四类此前"静默成功实则空内容 / 静默降级"的断点，修复后均应显式上抛清晰错误
或在缺配置时回退到用户默认：

- P0-1 图片 ``deepdoc_ocr``：``_process_image_ocr_static`` 误调不存在的
  ``DeepDocParser.aparse_bytes`` 且 ``except Exception`` 吞成空串 → 改调
  ``parse_bytes`` + 缺依赖/异常上抛 ``DocumentProcessingError``。
- P0-2 PDF OCR fallback：``_ocr_pdf_text_sync`` 在 Tesseract 缺失时逐页吞错返回空串
  → 前置 ``shutil.which('tesseract')`` 检查，缺失抛 ``RuntimeError``。
- P1-3 图片 ``vlm`` 策略 ``vlm_model`` 留空：此前直接抛错、不回退用户默认 VLM
  → 留空时经 ``model_config_port.get_user_default_model_name`` 回退，与视频路径对齐。
- P1-4 ES 索引 embedding dimension：``bulk_index_chunks`` 在 ``embedding_dim`` 缺失时
  静默兜底 1024 造成维度不匹配 → 改从首个含向量的 chunk 推断真实维度，仍缺失则抛错。
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.exceptions import DocumentProcessingError
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.services import document_pipeline
from novamind.engines.document.pipeline.document_loader import DocumentProcessor
from novamind.shared.storage import elasticsearch_client as es_module

pytestmark = pytest.mark.unit


def _make_document() -> SimpleNamespace:
    return SimpleNamespace(
        id=61,
        space_id=1,
        kb_id=1,
        file_hash="h",
        filename="x.png",
        file_type="png",
        storage={"minio_object_name": "obj"},
        uploader_id=1,
    )


def _silent_logger() -> SimpleNamespace:
    return SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )


# ---------------------------------------------------------------------------
# P0-1：图片 deepdoc_ocr 缺依赖/异常必须上抛，不再静默返回空串
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_deepdoc_ocr_missing_deps_raises():
    """DeepDoc OCR 引擎异常（如 cv2 ImportError）应上抛 DocumentProcessingError，
    而非被吞成空串导致文档以 0 chunk"成功"完成。"""

    class _BrokenDeepDocParser:
        async def parse_bytes(self, **kwargs):
            raise ImportError("No module named 'cv2'")

    import novamind.engines.document.integrations.deepdoc.core.engine as engine_mod

    with patch.object(engine_mod, "DeepDocParser", _BrokenDeepDocParser):
        with pytest.raises(DocumentProcessingError, match="DeepDoc OCR 解析失败"):
            await document_pipeline._process_image_ocr_static(
                document=_make_document(),
                file_content=b"\x89PNG fake",
                session=None,
                _logger=_silent_logger(),
            )


@pytest.mark.asyncio
async def test_image_deepdoc_ocr_calls_parse_bytes_without_parser_id():
    """确认调用的是 DeepDocParser.parse_bytes（非 aparse_bytes），且不传 parser_id。"""

    captured = {}

    class _SpyDeepDocParser:
        async def parse_bytes(self, **kwargs):
            captured["kwargs"] = kwargs
            return SimpleNamespace(full_text="OCR 文本", chunks=["c"])

    import novamind.engines.document.integrations.deepdoc.core.engine as engine_mod

    with patch.object(engine_mod, "DeepDocParser", _SpyDeepDocParser):
        text = await document_pipeline._process_image_ocr_static(
            document=_make_document(),
            file_content=b"\x89PNG fake",
            session=None,
            _logger=_silent_logger(),
        )

    assert "parser_id" not in captured["kwargs"], "不应再传 parser_id（按扩展名路由）"
    assert captured["kwargs"]["file_type"] == "png"
    assert text == "OCR 文本"


# ---------------------------------------------------------------------------
# P1-3：图片 vlm 策略 vlm_model 留空时回退用户默认 VLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_vlm_falls_back_to_user_default(monkeypatch):
    """vlm_model 留空时应回退 model_config_port.get_user_default_model_name，
    并把回退后的模型名传给 _generate_image_description，而非直接抛错。"""

    ctx = document_pipeline.PipelineContext(
        space=SimpleNamespace(owner_id=1),
        kb=None,
        pipeline_config={"parsing": {"image": {"strategy": "vlm"}}},
        embedding_config={"model": "emb-model", "dimension": 8},
    )

    async def _fake_load_ctx(session, document, task):
        return ctx

    async def _no_cancel(doc_id):
        return None

    # build_runtime_parsing_config 真实运行也行，这里 mock 为只给 vlm 策略、不含 vlm_model，
    # 解耦其内部实现细节。
    monkeypatch.setattr(
        document_pipeline, "build_runtime_parsing_config", lambda parsing, ft: {"image_strategy": "vlm"}
    )
    monkeypatch.setattr(document_pipeline, "load_pipeline_context", _fake_load_ctx)
    monkeypatch.setattr(document_pipeline, "_check_document_cancelled", _no_cancel)

    captured = {}

    async def _fake_gen_desc(**kwargs):
        captured["vlm_model_name"] = kwargs.get("vlm_model_name")
        return "图片描述文本"

    monkeypatch.setattr(document_pipeline, "_generate_image_description", _fake_gen_desc)

    async def _noop_persist(document, text, session, _logger):
        return None

    monkeypatch.setattr(document_pipeline, "persist_parsed_text", _noop_persist)

    async def _fake_tail(**kwargs):
        return {"chunk_count": 1, "split_strategy": "recursive", "total_questions": 0}

    monkeypatch.setattr(document_pipeline, "_run_post_parse_tail", _fake_tail)

    class _FakeSession:
        async def commit(self):
            return None

    class _FakeMCS:
        async def get_user_default_model_name(self, user_id, model_type):
            assert model_type == "vlm"
            return "default-vlm-model"

    task = SimpleNamespace(
        start_step=lambda *a, **k: None,
        finish_step=lambda *a, **k: None,
        mark_completed=lambda *a, **k: None,
    )

    # 不应抛错；且回退后的模型名应被传给描述生成
    await document_pipeline._process_image_document_static(
        document=_make_document(),
        file_content=b"\x89PNG fake",
        session=_FakeSession(),
        _logger=_silent_logger(),
        task=task,
        model_config_port=_FakeMCS(),
    )

    assert captured["vlm_model_name"] == "default-vlm-model"


@pytest.mark.asyncio
async def test_image_vlm_still_raises_when_no_default_vlm(monkeypatch):
    """vlm_model 留空且用户也无默认 VLM 时，仍应抛 DocumentProcessingError（显式失败）。"""

    ctx = document_pipeline.PipelineContext(
        space=SimpleNamespace(owner_id=1),
        kb=None,
        pipeline_config={"parsing": {"image": {"strategy": "vlm"}}},
        embedding_config={"model": "emb-model", "dimension": 8},
    )

    async def _fake_load_ctx(session, document, task):
        return ctx

    async def _no_cancel(doc_id):
        return None

    monkeypatch.setattr(
        document_pipeline, "build_runtime_parsing_config", lambda parsing, ft: {"image_strategy": "vlm"}
    )
    monkeypatch.setattr(document_pipeline, "load_pipeline_context", _fake_load_ctx)
    monkeypatch.setattr(document_pipeline, "_check_document_cancelled", _no_cancel)

    class _EmptyMCS:
        async def get_user_default_model_name(self, user_id, model_type):
            return None

    with pytest.raises(DocumentProcessingError, match="VLM"):
        await document_pipeline._process_image_document_static(
            document=_make_document(),
            file_content=b"\x89PNG fake",
            session=None,
            _logger=_silent_logger(),
            task=None,
            model_config_port=_EmptyMCS(),
        )


# ---------------------------------------------------------------------------
# P0-2：PDF OCR fallback 缺 Tesseract 时显式抛错
# ---------------------------------------------------------------------------


def test_pdf_ocr_raises_without_tesseract(monkeypatch):
    """ocr_enabled 走 OCR fallback 时，Tesseract 不在 PATH 应抛 RuntimeError，
    而非逐页吞错返回空串让扫描版 PDF 静默入库为空。"""

    def _fake_which(name):
        return None if name == "tesseract" else "/usr/bin/" + name

    monkeypatch.setattr("shutil.which", _fake_which)

    with pytest.raises(RuntimeError, match="Tesseract"):
        DocumentProcessor._ocr_pdf_text_sync(Path("any.pdf"))


# ---------------------------------------------------------------------------
# P1-4：bulk_index_chunks 从向量推断 embedding 维度
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_index_infers_dim_from_vectors():
    """embedding_dim 未传入时，应从首个含向量的 chunk 推断真实维度（768），
    避免静默兜底 1024 造成维度不匹配。"""

    captured = {}

    client = es_module.ElasticsearchClient.__new__(es_module.ElasticsearchClient)

    async def _spy_ensure_index_exists(space_id, embedding_dim=None):
        captured["embedding_dim"] = embedding_dim
        return f"space_{space_id}"

    client.ensure_index_exists = _spy_ensure_index_exists  # type: ignore[attr-defined]

    # es_client.bulk 返回全部 201 成功
    class _FakeES:
        async def bulk(self, operations):
            return {"items": [{"index": {"status": 201}} for _ in range(len(operations) // 2)]}

    client.es_client = _FakeES()  # type: ignore[attr-defined]

    chunks = [
        {"chunk_id": "c1", "content": "x", "embedding": [0.1] * 768},
        {"chunk_id": "c2", "content": "y", "embedding": [0.2] * 768},
    ]

    success = await es_module.ElasticsearchClient.bulk_index_chunks(
        client, space_id=1, chunks=chunks, embedding_dim=None
    )

    assert captured["embedding_dim"] == 768, "应从向量推断维度而非兜底 1024"
    assert success == 2


@pytest.mark.asyncio
async def test_bulk_index_raises_when_no_dim_and_no_vectors():
    """既无 embedding_dim 又无向量时，应拒绝建索引（抛 RuntimeError），不静默兜底 1024。"""

    client = es_module.ElasticsearchClient.__new__(es_module.ElasticsearchClient)
    client.default_embedding_dim = 1024  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError, match="无法确定 embedding 维度"):
        await es_module.ElasticsearchClient.bulk_index_chunks(
            client, space_id=1, chunks=[{"chunk_id": "c1", "content": "x"}], embedding_dim=None
        )