"""external_ocr 策略管道分支测试：异常映射与文本产出。

_process_image_ocr_external_static 是 external_ocr 策略的管线入口，
重点验证：凭证/文件错误 → 永久性（PermanentProcessingError，重试不可
修复）、服务瞬时失败 → 可重试（DocumentProcessingError）、成功路径
render_markdown 产出入库文本。OcrConnector 经 monkeypatch 替换，不调外网。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.engines.document.media.ocr.blocks import OcrBlock, OcrResult
from novamind.engines.document.media.ocr.qwen import OcrFileInvalidError, OcrRequestError
from novamind.features.knowledge_space.exceptions import (
    DocumentProcessingError,
    PermanentProcessingError,
)
from novamind.features.knowledge_space.services import document_pipeline, media_processing

pytestmark = pytest.mark.unit


def _document():
    return SimpleNamespace(id=1, uploader_id=9, file_type="pdf")


@pytest.fixture(autouse=True)
def _stub_ocr_config(monkeypatch):
    """宿主构造点返回测试配置（不读真实 YAML）。"""
    from novamind.engines.document.media.ocr.qwen import OcrEngineConfig

    monkeypatch.setattr(
        media_processing, "build_engine_ocr_config", lambda: OcrEngineConfig(
        api_key="k",
        model="qwen3.5-ocr",
        openai_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        dashscope_base_url="https://dashscope.aliyuncs.com/api/v1",
    )
    )


def _patch_recognize(monkeypatch, *, result=None, error=None, expect_task="multi_lan"):
    captured = {}

    async def fake_recognize(self, *, file_content, file_type, ocr_task=None):
        captured["task"] = ocr_task
        if error is not None:
            raise error
        return result

    from novamind.engines.document.media.ocr import connector as connector_mod

    monkeypatch.setattr(connector_mod.OcrConnector, "recognize", fake_recognize)
    return captured


class TestExternalOcrPipelineBranch:
    @pytest.mark.asyncio
    async def test_success_renders_markdown(self, monkeypatch):
        result = OcrResult(
            blocks=[
                OcrBlock(block_type="title", page_num=0, text="标题"),
                OcrBlock(block_type="text", page_num=0, text="正文"),
            ],
            page_count=1,
            protocol="dashscope",
        )
        _patch_recognize(monkeypatch, result=result)
        text = await document_pipeline._process_image_ocr_external_static(
            document=_document(),
            file_content=b"x",
            session=None,
            _logger=SimpleNamespace(info=lambda *a, **k: None),
            ocr_task="multi_lan",
        )
        assert "# 标题" in text and "正文" in text

    @pytest.mark.asyncio
    async def test_credentials_missing_is_permanent(self, monkeypatch):
        from novamind.engines.document.media.ocr import OcrCredentialsMissingError

        _patch_recognize(
            monkeypatch, error=OcrCredentialsMissingError("api_key 为空")
        )
        with pytest.raises(PermanentProcessingError, match="api_key"):
            await document_pipeline._process_image_ocr_external_static(
                document=_document(), file_content=b"x", session=None,
                _logger=SimpleNamespace(info=lambda *a, **k: None), ocr_task=None,
            )

    @pytest.mark.asyncio
    async def test_file_invalid_is_permanent(self, monkeypatch):
        _patch_recognize(monkeypatch, error=OcrFileInvalidError("损坏"))
        with pytest.raises(PermanentProcessingError, match="损坏"):
            await document_pipeline._process_image_ocr_external_static(
                document=_document(), file_content=b"x", session=None,
                _logger=SimpleNamespace(info=lambda *a, **k: None), ocr_task=None,
            )

    @pytest.mark.asyncio
    async def test_request_error_is_retryable(self, monkeypatch):
        _patch_recognize(monkeypatch, error=OcrRequestError("429"))
        with pytest.raises(DocumentProcessingError, match="可重试"):
            await document_pipeline._process_image_ocr_external_static(
                document=_document(), file_content=b"x", session=None,
                _logger=SimpleNamespace(info=lambda *a, **k: None), ocr_task=None,
            )


class _FakeProcessor:
    """split_text_items 桩：记录入参，按 \\n\\n 粗切。"""

    def __init__(self):
        self.calls: list[dict] = []

    async def split_text_items(self, text, strategy="recursive", **kwargs):
        self.calls.append({"strategy": strategy, **kwargs})
        return [(part, {}) for part in text.split("\n\n") if part.strip()]


class TestPdfExternalOcrBranch:
    """PDF 文本策略 external_ocr：OCR 产物须走 splitter 并保持结果三元组同构。"""

    @pytest.mark.asyncio
    async def test_pdf_ocr_result_is_split_and_wrapped(self, monkeypatch):
        result = OcrResult(
            blocks=[
                OcrBlock(block_type="title", page_num=0, text="第一章"),
                OcrBlock(block_type="text", page_num=1, text="扫描页正文"),
            ],
            page_count=2,
            protocol="openai",
        )
        captured = _patch_recognize(monkeypatch, result=result)
        processor = _FakeProcessor()
        parse_result = await document_pipeline._parse_pdf_with_external_ocr_static(
            document=_document(),
            file_content=b"%PDF-1.4",
            file_path=None,
            parse_config={"strategy": "external_ocr", "pdf_ocr_task": "document_parsing"},
            splitting_config={"strategy": "markdown", "chunk_size": 800},
            processor=processor,
            _logger=SimpleNamespace(info=lambda *a, **k: None),
        )
        # ocr_task 由 pdf_ocr_task 驱动（默认 doc parsing 时也显式透传）
        assert captured["task"] == "document_parsing"
        # 切分配置必须被尊重，且走的是与默认文本分支相同的 splitter
        assert processor.calls and processor.calls[0]["strategy"] == "markdown"
        assert processor.calls[0]["chunk_size"] == 800
        assert "第一章" in parse_result.full_text
        assert len(parse_result.chunks) == len(parse_result.full_text.split("\n\n"))
        assert parse_result.metadata["parser"] == "external_ocr"
        assert parse_result.metadata["ocr_protocol"] == "openai"
        assert parse_result.metadata["ocr_page_count"] == 2

    @pytest.mark.asyncio
    async def test_pdf_request_error_is_retryable(self, monkeypatch):
        _patch_recognize(monkeypatch, error=OcrRequestError("timeout"))
        with pytest.raises(DocumentProcessingError, match="可重试"):
            await document_pipeline._parse_pdf_with_external_ocr_static(
                document=_document(), file_content=b"x", file_path=None,
                parse_config={"strategy": "external_ocr"},
                splitting_config={},
                processor=_FakeProcessor(),
                _logger=SimpleNamespace(info=lambda *a, **k: None),
            )

    @pytest.mark.asyncio
    async def test_pdf_credentials_missing_is_permanent(self, monkeypatch):
        from novamind.engines.document.media.ocr import OcrCredentialsMissingError

        _patch_recognize(monkeypatch, error=OcrCredentialsMissingError("未配置"))
        with pytest.raises(PermanentProcessingError, match="未配置"):
            await document_pipeline._parse_pdf_with_external_ocr_static(
                document=_document(), file_content=b"x", file_path=None,
                parse_config={"strategy": "external_ocr"},
                splitting_config={},
                processor=_FakeProcessor(),
                _logger=SimpleNamespace(info=lambda *a, **k: None),
            )
