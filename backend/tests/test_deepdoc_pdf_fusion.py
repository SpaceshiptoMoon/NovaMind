"""DeepDoc PDF 逐框文字层/OCR 融合（full 模式）回归测试。

对齐 RAGFlow 上游 __ocr 的核心：每页 OCR.detect 拿框 → pdfplumber 文字层字符按坐标
匹配进框 → 逐框裁决（干净用文字层 / 乱码回退 OCR / 无字符走 OCR）→ 空框 recognize_batch。

用 mock OCR 直接测 _fuse_page，不依赖真实 OCR 模型，也不依赖 pandas（区别于
test_deepdoc_runtime.py 整模块 importorskip pandas）。
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from novamind.engines.document.integrations.deepdoc.core.capabilities import get_deepdoc_capabilities
from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser
from novamind.engines.document.integrations.deepdoc.pdf_artifacts import PdfArtifactExtractor
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    ParsingConfig,
    build_runtime_parsing_config,
)


class _FakeOCR:
    """替身 OCR：detect 返回预设检测框，recognize_batch 返回预设识别文本。"""

    parallel_devices = 1

    def __init__(self, detect_boxes, recognize_texts):
        self._detect_boxes = detect_boxes
        self._recognize_texts = list(recognize_texts)
        self.detect_calls = 0
        self.recognize_calls = 0
        self.last_recognize_count = 0

    def detect(self, img, device_id=None):
        self.detect_calls += 1
        return [(np.array(b, dtype=np.float32), ("", 0)) for b in self._detect_boxes]

    def get_rotate_crop_image(self, img, pts, device_id=None):
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

def test_insert_word_spaces_adds_english_gaps():
    """英文单词字符间隙过大时应补空格，中文不应被插空格。"""
    parser = RAGFlowPdfParser()
    chars = [
        _char("H", 0, 8, 0, 12),
        _char("e", 10, 16, 0, 12),
        _char("l", 18, 22, 0, 12),
        _char("l", 24, 28, 0, 12),
        _char("o", 30, 40, 0, 12),
        # 大 gap，应补空格
        _char("w", 70, 80, 0, 12),
        _char("o", 82, 90, 0, 12),
        _char("r", 92, 96, 0, 12),
        _char("l", 98, 102, 0, 12),
        _char("d", 104, 112, 0, 12),
        # 中文字符，不插空格
        _char("中", 120, 136, 0, 12),
        _char("文", 138, 154, 0, 12),
    ]
    result = parser._insert_word_spaces(chars)
    text = "".join(str(c.get("text", "")) for c in result)
    assert "Hello world" in text
    assert "中 文" not in text
    assert "中文" in text


@pytest.mark.unit
def test_zoom_retry_empty_page(monkeypatch):
    """_extract_fused_pages 对 zoom=2 未检出文字的页面递进重试到 zoom=6。"""
    parser = RAGFlowPdfParser()

    call_log = []

    def fake_fuse_page(img, chars, page_index, zoom):
        call_log.append(zoom)
        if zoom == 2:
            return []
        return [{"text": "found", "x0": 0, "x1": 10, "top": 0, "bottom": 10, "page_number": page_index}]

    monkeypatch.setattr(parser, "_fuse_page", fake_fuse_page)

    # 生成一个最小 1 页 PDF bytes
    import fitz
    from io import BytesIO

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((100, 700), "x")
    buffer = BytesIO()
    doc.save(buffer)
    doc.close()
    pdf_bytes = buffer.getvalue()

    image_list, fused_pages, layout_pages, fusion_meta = parser._extract_fused_pages(pdf_bytes)

    assert call_log == [2, 6]
    assert fusion_meta["effective_zooms"] == [6]
    assert len(fused_pages) == 1
    assert fused_pages[0]


@pytest.mark.unit
def test_ocr_parallel_devices_round_robin():
    """PARALLEL_DEVICES>1 时，_fuse_page 按页号轮询 device_id。"""
    parser = RAGFlowPdfParser()
    captured = []

    class _FakeOCR:
        parallel_devices = 3

        def detect(self, img, device_id=None):
            captured.append(device_id)
            return []

    parser._ocr = _FakeOCR()
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    parser._fuse_page(img, [], page_index=5, zoom=2)
    assert captured == [2]


class _FakeRotatingOCR:
    """模拟不同方向识别率不同的 OCR：原图方向无结果，顺时针 90° 有结果。"""

    parallel_devices = 1

    def __call__(self, img, device_id=0):
        h, w = img.shape[:2]
        # 原 crop 为 100x200（高>宽），90° 旋转后变为 200x100（高<宽）
        if h > w:
            return [], []
        box = np.array([[10, 10], [90, 10], [90, 30], [10, 30]], dtype=np.float32)
        return [box], [("cell", 0.95)]


@pytest.mark.unit
def test_evaluate_table_orientation_picks_90():
    """_evaluate_table_orientation 应选 OCR 得分最高的 90°。"""
    crop = Image.new("RGB", (100, 200), color=(255, 255, 255))
    angle, image, scores = PdfArtifactExtractor._evaluate_table_orientation(crop, _FakeRotatingOCR())
    assert angle == 90
    assert scores[0] == 0.0
    assert scores[90] > 0.0
    assert image.size == (200, 100)


@pytest.mark.unit
def test_rotated_ocr_boxes_map_to_page():
    """旋转重 OCR 后的 box 应正确映射回页面坐标，并替换 crop descriptor。"""
    from novamind.engines.document.integrations.deepdoc.pdf_artifacts import PdfArtifactExtractor

    crop = Image.new("RGB", (100, 200), color=(255, 255, 255))
    descriptor = {
        "page": 1,
        "bbox": {"x0": 50.0, "x1": 150.0, "top": 100.0, "bottom": 300.0},
        "crop": crop,
    }
    extractor = PdfArtifactExtractor(ocr=_FakeRotatingOCR())
    boxes = extractor._build_rotated_table_content_boxes(descriptor, extractor._ocr, zoom=2.0)

    assert len(boxes) == 1
    box = boxes[0]
    assert box.text == "cell"
    assert box.page == 1
    assert box.layout_type == "table"
    # 原 crop 中 box 映射后为 x0=10, x1=30, y0=109, y1=189；除以 zoom=2 再加页面 bbox 偏移
    assert abs(box.x0 - 55.0) < 1e-6
    assert abs(box.x1 - 65.0) < 1e-6
    assert abs(box.top - 154.5) < 1e-6
    assert abs(box.bottom - 194.5) < 1e-6
    assert descriptor["rotation_angle"] == 90
    assert descriptor["rotation_size"] == (100, 200)
    assert descriptor["crop"].size == (200, 100)


@pytest.mark.unit
def test_artifact_extractor_rotated_table_html(monkeypatch):
    """端到端：旋转表格 crop 后，产物 HTML 包含旋转识别出的文本。"""
    from dataclasses import dataclass
    from novamind.engines.document.integrations.deepdoc.pdf_artifacts import PdfArtifactExtractor

    @dataclass
    class _FakeBox:
        page: int
        x0: float
        x1: float
        top: float
        bottom: float
        text: str
        layout_type: str

    table_box = _FakeBox(
        page=1,
        x0=50.0,
        x1=150.0,
        top=100.0,
        bottom=300.0,
        text="",
        layout_type="table",
    )

    page_image = Image.new("RGB", (400, 600), color=(255, 255, 255))

    extractor = PdfArtifactExtractor(ocr=_FakeRotatingOCR())

    class _FakeTSR:
        def __call__(self, images, thr=0.2):
            # 返回一个 table row + 一个 table column，覆盖 cell box 区域
            return [[
                {"label": "table row", "x0": 5.0, "x1": 95.0, "top": 5.0, "bottom": 35.0},
                {"label": "table column", "x0": 5.0, "x1": 95.0, "top": 5.0, "bottom": 35.0},
            ]]

    monkeypatch.setattr(extractor, "_get_tsr_recognizer", lambda: _FakeTSR())

    artifacts = extractor.extract(
        [table_box],
        page_images={1: page_image},
        zoom=2.0,
    )

    assert len(artifacts["tables"]) == 1
    table = artifacts["tables"][0]
    assert table["rotation_angle"] == 90
    assert "cell" in table["html"]
    assert table["html_source"] == "tsr_model"
    assert table["table_structure"]["is_english"] is True


@pytest.mark.unit
def test_cross_page_table_row_offsets(monkeypatch):
    """跨页表格的 TSR row 编号应连续，不应每页重新从 0 开始。"""
    from types import SimpleNamespace

    extractor = PdfArtifactExtractor()

    class _FakeTSR:
        def __call__(self, images, thr=0.2):
            return [
                [
                    {"label": "table row", "x0": 0, "x1": 100, "top": 0, "bottom": 50},
                    {"label": "table column", "x0": 0, "x1": 100, "top": 0, "bottom": 50},
                ],
                [
                    {"label": "table row", "x0": 0, "x1": 100, "top": 0, "bottom": 50},
                    {"label": "table column", "x0": 0, "x1": 100, "top": 0, "bottom": 50},
                ],
            ]

    monkeypatch.setattr(extractor, "_get_tsr_recognizer", lambda: _FakeTSR())

    box1 = SimpleNamespace(page=1, x0=10, x1=90, top=10, bottom=30, text="Page1", layout_type="table")
    box2 = SimpleNamespace(page=2, x0=10, x1=90, top=10, bottom=30, text="Page2", layout_type="table")
    descriptors = [
        {"page": 1, "bbox": {"x0": 0, "x1": 100, "top": 0, "bottom": 50}, "crop": Image.new("RGB", (100, 50))},
        {"page": 2, "bbox": {"x0": 0, "x1": 100, "top": 0, "bottom": 50}, "crop": Image.new("RGB", (100, 50))},
    ]

    boxes, meta = extractor._infer_structured_boxes_from_tsr_model(
        [box1, box2],
        crop_descriptors=descriptors,
        zoom=1.0,
    )

    rs = sorted(int(b["R"]) for b in boxes)
    assert rs == [0, 1]
    assert meta["crosspage_row_offset"] == [1, 2]
