"""OcrConnector 路由解析与协议分发的单元测试（不调外网）。"""
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

from novamind.engines.document.media.ocr.connector import (
    OcrConnector,
    OcrCredentialsMissingError,
    OcrRoute,
)
from novamind.engines.document.media.ocr.qwen import (
    OcrEngineConfig,
    OcrFileInvalidError,
    OcrRequestError,
)
from novamind.engines.document.media.ocr.blocks import OcrBlock, OcrResult

pytestmark = pytest.mark.unit

CONFIG = OcrEngineConfig(api_key="test-key")


def _result(protocol: str = "dashscope", text: str = "内容") -> OcrResult:
    return OcrResult(
        blocks=[OcrBlock(block_type="text", page_num=0, text=text)],
        model="qwen3.5-ocr",
        protocol=protocol,
    )


class TestResolveRoute:
    def test_pdf_defaults_document_parsing(self):
        route = OcrConnector(CONFIG).resolve_route(file_type="pdf")
        assert route.protocol == "openai"
        assert route.ocr_task == "document_parsing"
        assert route.base_url == CONFIG.openai_base_url
        assert route.api_key == "test-key"

    def test_pdf_multi_lan_uses_render_dpi(self):
        route = OcrConnector(CONFIG).resolve_route(file_type="PDF", ocr_task="multi_lan")
        assert route.protocol == "dashscope"
        assert route.ocr_task == "multi_lan"
        assert route.render_dpi == 300

    def test_image_routes_multi_lan(self):
        connector = OcrConnector(CONFIG)
        for ext in ("png", "JPG", "jpeg", "webp", "bmp"):
            route = connector.resolve_route(file_type=ext)
            assert route.protocol == "dashscope"
            assert route.ocr_task == "multi_lan"

    def test_image_rejects_document_parsing(self):
        with pytest.raises(OcrCredentialsMissingError, match="multi_lan"):
            OcrConnector(CONFIG).resolve_route(file_type="png", ocr_task="document_parsing")

    def test_missing_api_key_raises(self):
        with pytest.raises(OcrCredentialsMissingError, match="api_key"):
            OcrConnector(OcrEngineConfig(api_key="")).resolve_route(file_type="pdf")

    def test_missing_engine_config_raises(self):
        with pytest.raises(OcrCredentialsMissingError, match="未注入"):
            OcrConnector(None).resolve_route(file_type="pdf")

    def test_bad_task_raises(self):
        with pytest.raises(OcrCredentialsMissingError, match="不受支持"):
            OcrConnector(CONFIG).resolve_route(file_type="pdf", ocr_task="ocr_v2")

    def test_unsupported_file_type_raises(self):
        with pytest.raises(OcrFileInvalidError, match="docx"):
            OcrConnector(CONFIG).resolve_route(file_type="docx")


class TestRecognizeDispatch:
    @pytest.mark.asyncio
    async def test_pdf_dispatches_document_parsing(self, monkeypatch):
        captured = {}

        async def fake_parse(*, file_content, config):
            captured["content"] = file_content
            captured["config"] = config
            return _result(protocol="openai")

        import novamind.engines.document.media.ocr.connector as mod

        monkeypatch.setattr(
            "novamind.engines.document.media.ocr.qwen.parse_document_with_qwen_ocr", fake_parse
        )
        result = await OcrConnector(CONFIG).recognize(file_content=b"%PDF", file_type="pdf")
        assert result.protocol == "openai"
        assert captured["content"] == b"%PDF"
        assert captured["config"] is CONFIG

    @pytest.mark.asyncio
    async def test_image_dispatches_multi_lan(self, monkeypatch):
        captured = {}

        async def fake_recognize(*, image_bytes, mime_type, config):
            captured["mime"] = mime_type
            return _result()

        monkeypatch.setattr(
            "novamind.engines.document.media.ocr.qwen.recognize_image_with_qwen_ocr",
            fake_recognize,
        )
        result = await OcrConnector(CONFIG).recognize(
            file_content=b"\x89PNG", file_type="png")
        assert result.protocol == "dashscope"
        assert captured["mime"] == "image/png"

    @pytest.mark.asyncio
    async def test_pdf_multi_lan_merges_pages_single_page_failure_tolerated(self, monkeypatch):
        fake_pages = [(b"png0", 0), (b"png1", 1)]

        def fake_render(content, dpi):
            assert dpi == 300
            return fake_pages

        calls: list[int] = []

        async def fake_recognize(*, image_bytes, mime_type, config):
            page = fake_pages[calls[-1]][0] if calls else b""
            calls.append(len(calls))
            if image_bytes == b"png0":
                raise OcrRequestError("boom")
            return _result(text=f"第{image_bytes.decode()}文本")

        monkeypatch.setattr(
            "novamind.engines.document.media.ocr.qwen.render_pdf_page_images", fake_render
        )
        monkeypatch.setattr(
            "novamind.engines.document.media.ocr.qwen.recognize_image_with_qwen_ocr",
            fake_recognize,
        )
        result = await OcrConnector(CONFIG).recognize(
            file_content=b"%PDF", file_type="pdf", ocr_task="multi_lan")
        # 第 0 页失败被容忍，第 1 页 page_num 以渲染下标归一
        assert result.page_count == 2
        assert [b.page_num for b in result.blocks] == [1]
        assert result.blocks[0].text == "第png1文本"

    @pytest.mark.asyncio
    async def test_pdf_multi_lan_all_pages_fail_raises(self, monkeypatch):
        monkeypatch.setattr(
            "novamind.engines.document.media.ocr.qwen.render_pdf_page_images",
            lambda content, dpi: [(b"png0", 0)],
        )

        async def fake_recognize(**kw):
            raise OcrRequestError("boom")

        monkeypatch.setattr(
            "novamind.engines.document.media.ocr.qwen.recognize_image_with_qwen_ocr",
            fake_recognize,
        )
        with pytest.raises(OcrRequestError, match="均失败"):
            await OcrConnector(CONFIG).recognize(
                file_content=b"%PDF", file_type="pdf", ocr_task="multi_lan")

    @pytest.mark.asyncio
    async def test_recognize_without_config_raises(self):
        with pytest.raises(OcrCredentialsMissingError, match="未注入"):
            await OcrConnector(None).recognize(file_content=b"x", file_type="pdf")
