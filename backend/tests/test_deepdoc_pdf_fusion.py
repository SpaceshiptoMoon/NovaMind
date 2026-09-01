"""DeepDoc PDF 逐框文字层/OCR 融合（full 模式）回归测试。

对齐 RAGFlow 上游 __ocr 的核心：每页 OCR.detect 拿框 → pdfplumber 文字层字符按坐标
匹配进框 → 逐框裁决（干净用文字层 / 乱码回退 OCR / 无字符走 OCR）→ 空框 recognize_batch。

用 mock OCR 直接测 _fuse_page，不依赖真实 OCR 模型，也不依赖 pandas（区别于
test_deepdoc_runtime.py 整模块 importorskip pandas）。
"""
from __future__ import annotations

import numpy as np
import pytest

from novamind.engines.document.integrations.deepdoc.core.capabilities import get_deepdoc_capabilities
from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    ParsingConfig,
    build_runtime_parsing_config,
)


class _FakeOCR:
    """替身 OCR：detect 返回预设检测框，recognize_batch 返回预设识别文本。"""

    def __init__(self, detect_boxes, recognize_texts):
        self._detect_boxes = detect_boxes
        self._recognize_texts = list(recognize_texts)
        self.detect_calls = 0
        self.recognize_calls = 0
        self.last_recognize_count = 0

    def detect(self, img, device_id=None):
        self.detect_calls += 1
        return [(np.array(b, dtype=np.float32), ("", 0)) for b in self._detect_boxes]

    def get_rotate_crop_image(self, img, pts):
        return np.zeros((16, 32, 3), dtype=np.uint8)

    def recognize_batch(self, crops, device_id=None):
        self.recognize_calls += 1
        self.last_recognize_count = len(crops)
        return self._recognize_texts[: len(crops)]


def _char(text, x0, x1, top, bottom, fontname="Arial"):
    return {
        "text": text,
        "x0": float(x0),
        "x1": float(x1),
        "top": float(top),
        "bottom": float(bottom),
        "width": float(x1 - x0),
        "height": float(bottom - top),
        "fontname": fontname,
    }


@pytest.mark.unit
def test_per_box_fusion_text_layer_preferred_over_ocr():
    """框内有干净文字层字符 → 用文字层文字，该框不进 recognize_batch；
    框内无字符 → 走 OCR。"""
    parser = RAGFlowPdfParser()
    # 两个检测框（像素坐标，zoom=2 → 逻辑坐标 /2）
    # 框 A: 像素 (0,0)-(100,40) → 逻辑 (0,0,50,20)；框 B: (0,50)-(100,90) → 逻辑 (0,25,50,45)
    parser._ocr = _FakeOCR(
        detect_boxes=[[[0, 0], [100, 0], [100, 40], [0, 40]], [[0, 50], [100, 50], [100, 90], [0, 90]]],
        recognize_texts=["OCR TEXT"],
    )
    # 框 A 内放干净文字层字符；框 B 不给字符
    chars = [_char("Hello", 5, 45, 4, 18)]
    img = np.zeros((200, 200, 3), dtype=np.uint8)

    blocks = parser._fuse_page(img, chars, page_index=0, zoom=2)

    by_source = {b["ocr_source"] for b in blocks}
    text_by_source = {b["ocr_source"]: b["text"] for b in blocks}
    assert "text_layer" in by_source, f"应有文字层框，got {by_source}"
    assert "vendored_ocr" in by_source, f"应有 OCR 框，got {by_source}"
    assert "Hello" in text_by_source["text_layer"]
    assert text_by_source["vendored_ocr"] == "OCR TEXT"
    # recognize_batch 只被调一次（仅空框那一批）
    assert parser._ocr.recognize_calls == 1
    assert parser._ocr.last_recognize_count == 1


@pytest.mark.unit
def test_garbled_box_falls_back_to_ocr():
    """框内文字层字符全为 PUA 乱码（_is_garbled_char 命中）→ 清空文字层，该框走 OCR。"""
    parser = RAGFlowPdfParser()
    parser._ocr = _FakeOCR(
        detect_boxes=[[[0, 0], [100, 0], [100, 40], [0, 40]]],
        recognize_texts=["OCR CLEAN"],
    )
    # PUA 字符  会被 _is_garbled_char 判为乱码
    chars = [_char("", 5, 45, 4, 18, fontname="SubsetFont+ABCDEF+Georgia")]
    img = np.zeros((200, 200, 3), dtype=np.uint8)

    blocks = parser._fuse_page(img, chars, page_index=0, zoom=2)

    assert len(blocks) == 1
    assert blocks[0]["ocr_source"] == "vendored_ocr"
    assert blocks[0]["text"] == "OCR CLEAN"
    assert parser._ocr.recognize_calls == 1


@pytest.mark.unit
def test_no_chars_box_uses_ocr():
    """框内无任何文字层字符 → 直接走 OCR。"""
    parser = RAGFlowPdfParser()
    parser._ocr = _FakeOCR(
        detect_boxes=[[[0, 0], [100, 0], [100, 40], [0, 40]]],
        recognize_texts=["ONLY OCR"],
    )
    img = np.zeros((200, 200, 3), dtype=np.uint8)

    blocks = parser._fuse_page(img, page_chars=[], page_index=0, zoom=2)

    assert len(blocks) == 1
    assert blocks[0]["text"] == "ONLY OCR"
    assert blocks[0]["ocr_source"] == "vendored_ocr"


@pytest.mark.unit
def test_empty_text_after_ocr_filtered_out():
    """OCR 识别返回空串的框被过滤掉（不产出空块）。"""
    parser = RAGFlowPdfParser()
    parser._ocr = _FakeOCR(
        detect_boxes=[[[0, 0], [100, 0], [100, 40], [0, 40]]],
        recognize_texts=[""],  # OCR 识别为空
    )
    img = np.zeros((200, 200, 3), dtype=np.uint8)

    blocks = parser._fuse_page(img, page_chars=[], page_index=0, zoom=2)
    assert blocks == []


@pytest.mark.unit
def test_build_vision_strategy_text_layer_and_fused():
    """_build_vision_strategy 识别 text_layer / fused / vendored-ocr 来源。"""
    s = RAGFlowPdfParser._build_vision_strategy(["text_layer"], "onnx")
    assert s == "text-layer+onnx-layout"
    s = RAGFlowPdfParser._build_vision_strategy(["text_layer", "vendored_ocr"], "heuristic")
    assert s == "fused+heuristic-layout"
    s = RAGFlowPdfParser._build_vision_strategy(["vendored_ocr"], "onnx")
    assert s == "vendored-ocr+onnx-layout"


@pytest.mark.unit
def test_call_alias_layout_vision_routes_to_full(monkeypatch):
    """__call__("layout")/("vision") 兼容别名 → _parse_full。"""
    parser = RAGFlowPdfParser()
    calls = []
    monkeypatch.setattr(parser, "_parse_full", lambda filename, *, chunk_size: calls.append(("full", chunk_size)) or _fake_result())
    monkeypatch.setattr(parser, "_parse_plain", lambda filename, *, chunk_size: calls.append(("plain", chunk_size)) or _fake_result())
    parser(b"pdf", pdf_mode="layout", chunk_size=500)
    parser(b"pdf", pdf_mode="vision", chunk_size=500)
    parser(b"pdf", pdf_mode="full", chunk_size=500)
    parser(b"pdf", pdf_mode="plain", chunk_size=500)
    assert [c[0] for c in calls] == ["full", "full", "full", "plain"]


class _FakeResult:
    full_text = ""
    chunks = []
    metadata = {}


def _fake_result():
    return _FakeResult()


@pytest.mark.unit
def test_capabilities_pdf_modes_collapsed_to_full():
    """capabilities 只剩 plain + full + 6 远程，不再有 layout/vision。"""
    caps = get_deepdoc_capabilities()
    modes = caps["pdf_modes"]
    assert "full" in modes
    assert "plain" in modes
    assert "layout" not in modes
    assert "vision" not in modes
    # full 依赖 vision 运行时（与旧 vision 同门禁）
    assert "missing" in modes["full"]


@pytest.mark.unit
def test_build_runtime_pdf_full_emits_full_mode():
    """build_runtime_parsing_config：parser=full → deepdoc_pdf_mode=full, parser_id=pdf_full。"""
    rc = build_runtime_parsing_config({"text": {"pdf": {"strategy": "deepdoc", "parser": "full"}}}, "pdf")
    assert rc["deepdoc_pdf_mode"] == "full"
    assert rc["deepdoc_parser_id"] == "pdf_full"


@pytest.mark.unit
def test_legacy_layout_vision_migrate_to_full():
    """旧 deepdoc_parser_id=pdf_layout/pdf_vision 与 deepdoc_pdf_mode=layout/vision 迁移到 full。"""
    for legacy_id in ("pdf_layout", "pdf_vision"):
        m = ParsingConfig.model_validate({"strategy": "deepdoc", "deepdoc_parser_id": legacy_id})
        assert m.text.pdf.parser == "full", f"{legacy_id} 应迁移到 full"
    for legacy_mode in ("layout", "vision"):
        m = ParsingConfig.model_validate({"strategy": "deepdoc", "deepdoc_pdf_mode": legacy_mode})
        assert m.text.pdf.parser == "full", f"deepdoc_pdf_mode={legacy_mode} 应迁移到 full"
        assert m.deepdoc_pdf_mode == "full"


@pytest.mark.unit
def test_legacy_plain_stays_plain():
    m = ParsingConfig.model_validate({"strategy": "deepdoc", "deepdoc_parser_id": "pdf_plain"})
    assert m.text.pdf.parser == "plain"