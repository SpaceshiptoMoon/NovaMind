"""qwen3.5-ocr 客户端归一逻辑的单元测试（不调外网）。

mock 模式对齐 test_asr_connector：monkeypatch 打补丁到目标模块符号，
Fake 响应用 SimpleNamespace/model_dump 桩构造。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

from novamind.engines.document.media.ocr.qwen import (
    OcrEngineConfig,
    OcrFileInvalidError,
    OcrRequestError,
    _extract_multi_lan_text,
    parse_document_with_qwen_ocr,
    recognize_image_with_qwen_ocr,
    render_pdf_page_images,
)

pytestmark = pytest.mark.unit

CONFIG = OcrEngineConfig(
        api_key="test-key",
        model="qwen3.5-ocr",
        openai_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        dashscope_base_url="https://dashscope.aliyuncs.com/api/v1",
    )


def _layout(**overrides):
    base = {
        "type": "text",
        "pageNum": 0,
        "pos": [{"x": 10, "y": 20}, {"x": 110, "y": 20}, {"x": 110, "y": 40}, {"x": 10, "y": 40}],
        "markdownContent": "内容",
        "text": "内容",
    }
    base.update(overrides)
    return base


def _responses_payload(layouts):
    """构造 responses 响应的 model_dump() 形态（output→content→ocr_result）。"""
    return {"output": [{"content": [{"ocr_result": {"layouts": layouts}}]}]}


def _patch_openai(monkeypatch, layouts=None, error: Exception | None = None, payload=None):
    dump = payload if payload is not None else _responses_payload(layouts or [])

    def create(**kw):
        if error is not None:
            raise error
        return SimpleNamespace(model_dump=lambda: dump)

    fake_client = SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr("openai.OpenAI", lambda **kw: fake_client)


class TestParseDocument:
    @pytest.mark.asyncio
    async def test_maps_layouts_to_blocks(self, monkeypatch):
        layouts = [
            _layout(type="title", pageNum=0, markdownContent="# 标题", text="标题"),
            _layout(type="formula", pageNum=1, markdownContent="$$x+1$$", text="x+1"),
            _layout(type="whatever", pageNum=2, text="未知类型"),
        ]
        _patch_openai(monkeypatch, layouts=layouts)

        result = await parse_document_with_qwen_ocr(file_content=b"%PDF-fake", config=CONFIG)
        assert result.protocol == "openai"
        assert result.model == CONFIG.model
        assert result.page_count == 3
        assert [b.block_type for b in result.blocks] == ["title", "formula", "text"]
        assert result.blocks[1].page_num == 1
        assert result.blocks[0].bbox == (10.0, 20.0, 110.0, 40.0)

    @pytest.mark.asyncio
    async def test_falls_back_to_text_and_drops_empty(self, monkeypatch):
        layouts = [
            _layout(markdownContent="", text="纯文本兜底"),
            _layout(markdownContent="", text="   "),
        ]
        _patch_openai(monkeypatch, layouts=layouts)

        result = await parse_document_with_qwen_ocr(file_content=b"%PDF-fake", config=CONFIG)
        assert len(result.blocks) == 1
        assert result.blocks[0].markdown == ""
        assert result.blocks[0].text == "纯文本兜底"

    @pytest.mark.asyncio
    async def test_page_num_negative_clamped_and_bad_parse_zero(self, monkeypatch):
        _patch_openai(monkeypatch, layouts=[_layout(pageNum=-3), _layout(pageNum="bad")])

        result = await parse_document_with_qwen_ocr(file_content=b"%PDF-fake", config=CONFIG)
        assert [b.page_num for b in result.blocks] == [0, 0]
        assert result.page_count == 1

    @pytest.mark.asyncio
    async def test_missing_ocr_result_raises(self, monkeypatch):
        _patch_openai(monkeypatch, payload={"output": [{"content": [{"type": "text"}]}]})

        with pytest.raises(OcrRequestError, match="ocr_result"):
            await parse_document_with_qwen_ocr(file_content=b"%PDF-fake", config=CONFIG)

    @pytest.mark.asyncio
    async def test_network_error_wrapped(self, monkeypatch):
        _patch_openai(monkeypatch, error=ConnectionError("refused"))

        with pytest.raises(OcrRequestError, match="document_parsing"):
            await parse_document_with_qwen_ocr(file_content=b"%PDF-fake", config=CONFIG)


class TestExtractMultiLanText:
    def test_joins_text_parts(self):
        content = [{"text": "第一段\n"}, {"text": "第二段"}]
        output = {"choices": [{"message": SimpleNamespace(content=content)}]}
        assert _extract_multi_lan_text(output) == "第一段\n第二段"

    def test_malformed_degrades_to_str(self):
        text = _extract_multi_lan_text(SimpleNamespace(unexpected="shape"))
        assert isinstance(text, str)


class TestRecognizeImage:
    @pytest.mark.asyncio
    async def test_returns_single_block(self, monkeypatch):
        def fake_call(**kw):
            return SimpleNamespace(
                status_code=200,
                output={"choices": [{"message": SimpleNamespace(content=[{"text": "识别文本"}])}]},
                message=None,
            )

        import dashscope

        monkeypatch.setattr(dashscope.MultiModalConversation, "call", staticmethod(fake_call))

        result = await recognize_image_with_qwen_ocr(
            image_bytes=b"\x89PNG fake", mime_type="image/png", config=CONFIG
        )
        assert result.protocol == "dashscope"
        assert result.page_count == 1
        assert len(result.blocks) == 1
        assert result.blocks[0].block_type == "text"
        assert result.blocks[0].text == "识别文本"

    @pytest.mark.asyncio
    async def test_non_200_raises(self, monkeypatch):
        def fake_call(**kw):
            return SimpleNamespace(status_code=429, output=None, message="quota")

        import dashscope

        monkeypatch.setattr(dashscope.MultiModalConversation, "call", staticmethod(fake_call))

        with pytest.raises(OcrRequestError, match="429"):
            await recognize_image_with_qwen_ocr(
                image_bytes=b"\x89PNG", mime_type="image/png", config=CONFIG
            )


class TestRenderPdfPageImages:
    def test_two_page_pdf(self):
        import fitz

        doc = fitz.open()
        for _ in range(2):
            doc.new_page()
        pdf_bytes = doc.tobytes()
        doc.close()

        pages = render_pdf_page_images(pdf_bytes, dpi=72)
        assert [p[1] for p in pages] == [0, 1]
        assert all(p[0].startswith(b"\x89PNG") for p in pages)

    def test_invalid_bytes_raises(self):
        with pytest.raises(OcrFileInvalidError):
            render_pdf_page_images(b"not a pdf", dpi=72)
