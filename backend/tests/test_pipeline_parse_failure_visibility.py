"""解析管道静默失败修复回归测试（P0 + P1）。

覆盖四类此前"静默成功实则空内容 / 静默降级兜底"的断点，修复后均应显式上抛清晰错误，
不做兜底（兜底会让解析路径不可追踪）：

- P0-1 图片 ``deepdoc_ocr``：``_process_image_ocr_static`` 误调不存在的
  ``DeepDocParser.aparse_bytes`` 且 ``except Exception`` 吞成空串 → 改调
  ``parse_bytes`` + 缺依赖/异常上抛 ``DocumentProcessingError``。
- P0-2 PDF OCR fallback：``_ocr_pdf_text_sync`` 在 Tesseract 缺失时逐页吞错返回空串
  → 前置 ``shutil.which('tesseract')`` 检查，缺失抛 ``RuntimeError``。
- P1-3 图片 ``vlm`` 策略 ``vlm_model`` 留空：不做"回退用户默认 VLM"兜底，直接抛
  ``DocumentProcessingError``，要求用户在解析配置中显式选择（保证路径可追踪）。
- P1-4 ES 索引 embedding dimension：``bulk_index_chunks`` 在 ``embedding_dim`` 缺失时
  不静默兜底 1024、也不从向量推断，直接抛 ``RuntimeError`` 要求配置补齐。
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
# P1-3：图片 vlm 策略 vlm_model 留空时不兜底，直接抛错
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_vlm_raises_when_vlm_model_empty(monkeypatch):
    """vlm_model 留空时必须显式抛 DocumentProcessingError，不做"回退用户默认 VLM"兜底。

    即使 model_config_port 能提供默认 VLM 也不应回退——兜底会让解析路径不可追踪
    （无法从配置看出实际用了哪个模型）。留空即抛错，要求用户在解析配置中显式选择。
    """

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

    # mock 为只给 vlm 策略、不含 vlm_model，解耦 build_runtime_parsing_config 内部细节。
    monkeypatch.setattr(
        document_pipeline, "build_runtime_parsing_config", lambda parsing, ft: {"image_strategy": "vlm"}
    )
    monkeypatch.setattr(document_pipeline, "load_pipeline_context", _fake_load_ctx)
    monkeypatch.setattr(document_pipeline, "_check_document_cancelled", _no_cancel)

    class _MCSWithDefault:
        async def get_user_default_model_name(self, user_id, model_type):
            return "default-vlm-model"  # 有默认，但不应被回退使用

    with pytest.raises(DocumentProcessingError, match="VLM"):
        await document_pipeline._process_image_document_static(
            document=_make_document(),
            file_content=b"\x89PNG fake",
            session=None,
            _logger=_silent_logger(),
            task=None,
            model_config_port=_MCSWithDefault(),
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
# P1-4：bulk_index_chunks 缺 embedding_dim 时显式抛错，不兜底
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_index_raises_when_embedding_dim_none():
    """embedding_dim 未传入时必须抛 RuntimeError，不做向量推断或 1024 兜底。

    即使 chunks 含向量也不应从中推断维度——兜底会让索引维度不可追踪
    （无法从空间配置看出索引实际维度）。维度缺失即显式抛错，要求配置补齐。
    """

    client = es_module.ElasticsearchClient.__new__(es_module.ElasticsearchClient)
    client.default_embedding_dim = 1024  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError, match="无法确定 embedding 维度"):
        await es_module.ElasticsearchClient.bulk_index_chunks(
            client,
            space_id=1,
            chunks=[{"chunk_id": "c1", "content": "x", "embedding": [0.1] * 768}],
            embedding_dim=None,
        )