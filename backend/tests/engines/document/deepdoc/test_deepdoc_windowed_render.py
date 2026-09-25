"""分窗批处理回归测试（2026-09-25）。

内存主防线：_extract_fused_pages 整本渲染驻留时 300 页扫描件 ≈4GB（zoom=3 A4
约 13MB/页），与 arq max_jobs=3 并发相乘直接撞顶。分窗后「渲染→OCR 融合→
layout 推理→释放」按窗滚动，驻留上限 = 单窗（DEEPDOC_RENDER_WINDOW_SIZE，
默认 16 页），与文档总页数无关。

关键约束（本文件锁死）：
- fused_pages / layout_pages / image_list 页数与全书页序不变；
- position_tag 页码保持全书 1-based（分窗不得引入窗内局部页码）；
- layout 推理按窗调用（窗 2 页 + 3 页文档 → forward 2 次）；
- 返回的 image_list 是 shape 占位（真实 buffer 已释放），满足 apply_layouts
  的 shape 读取；
- 模型不可用/窗内推理失败回退启发式，契约与原单次推理一致。
"""
from __future__ import annotations

from io import BytesIO

import pytest

pytest.importorskip("fitz")

import fitz
from novamind.engines.document.integrations.deepdoc.parsers.pdf import (
    RAGFlowPdfParser,
    _render_window_size,
)
from novamind.engines.document.integrations.deepdoc.vision.layout_recognizer import (
    LayoutRecognizer4YOLOv10,
)

pytestmark = pytest.mark.unit


def _make_pdf(page_count: int) -> bytes:
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page()
        page.insert_text((72, 100), f"page {i + 1} sample body text", fontsize=12)
    buf = BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def _fake_fuse_page(parser, char_text: str = "body") -> None:
    def fake_fuse(img, chars, page_index, zoom, device_id=None):
        return [
            {
                "text": f"{char_text} {page_index}",
                "x0": 10,
                "x1": 60,
                "top": 10,
                "bottom": 20,
                "page_number": page_index,
                "ocr_source": "text_layer",
            }
        ]

    parser._fuse_page = fake_fuse
    parser._extract_page_chars = lambda pages, idx: []


def test_render_window_size_env_parsing(monkeypatch):
    """env 解析：默认 16；非整数/负数回退默认；1 合法（逐页）。"""
    monkeypatch.delenv("DEEPDOC_RENDER_WINDOW_SIZE", raising=False)
    assert _render_window_size() == 16
    monkeypatch.setenv("DEEPDOC_RENDER_WINDOW_SIZE", "2")
    assert _render_window_size() == 2
    monkeypatch.setenv("DEEPDOC_RENDER_WINDOW_SIZE", "1")
    assert _render_window_size() == 1
    monkeypatch.setenv("DEEPDOC_RENDER_WINDOW_SIZE", "abc")
    assert _render_window_size() == 16
    monkeypatch.setenv("DEEPDOC_RENDER_WINDOW_SIZE", "0")
    assert _render_window_size() == 16


def test_windowed_extraction_forwards_per_window(monkeypatch):
    """3 页文档窗 2 → layout forward 调 2 次；页序/页码全书保持。"""
    parser = RAGFlowPdfParser()
    _fake_fuse_page(parser)
    forward_calls: list[int] = []

    class FakeLayout(LayoutRecognizer4YOLOv10):
        def __init__(self):
            self.loaded = True
            self.garbage_layouts = ["footer", "header", "reference"]
            self.center = True
            self.input_shape = (640, 640)
            self.label_list = self.labels

        def load(self):
            pass

        def ensure_loaded(self):
            pass

        def forward(self, images, thr=0.2, batch_size=16):
            forward_calls.append(len(images))
            return [
                [
                    {"type": "text", "score": 0.9, "bbox": [0.0, 0.0, float(i.shape[1]), float(i.shape[0])]}
                ]
                for i in images
            ]

    parser._layout_recognizer = FakeLayout()
    monkeypatch.setenv("DEEPDOC_RENDER_WINDOW_SIZE", "2")

    image_list, fused_pages, layout_pages, meta = parser._extract_fused_pages(_make_pdf(3))

    assert forward_calls == [2, 1], f"窗大小应切为 2+1: {forward_calls}"
    assert len(fused_pages) == len(layout_pages) == len(image_list) == 3
    assert meta["layout_source"] == "onnx"
    # image_list 是 shape 占位（真实 buffer 已随窗释放）
    assert all(not hasattr(x, "tobytes") for x in image_list)
    assert all(x.shape[0] > 0 for x in image_list)
    # fused 文本的 page_number 保持全书 0-based 页索引
    page_numbers = [entry["page_number"] for page in fused_pages for entry in page]
    assert page_numbers == [0, 1, 2]


def test_windowed_parse_full_keeps_book_wide_position_tags(monkeypatch):
    """完整 full 流水线在分窗下：position_tag 页码全书 1-based、reading_order 完整。

    锁死「分窗不得把页号缩成窗内局部页号」——引用溯源链路按页码定位原文，
    窗内页号漂移会让引用指错页。"""
    parser = RAGFlowPdfParser()

    class FakeLayout(LayoutRecognizer4YOLOv10):
        def __init__(self):
            self.loaded = True
            self.garbage_layouts = ["footer", "header", "reference"]
            self.center = True
            self.input_shape = (640, 640)
            self.label_list = self.labels

        def load(self):
            pass

        def ensure_loaded(self):
            pass

        def forward(self, images, thr=0.2, batch_size=16):
            return [
                [{"type": "text", "score": 0.9, "bbox": [0.0, 0.0, float(i.shape[1]), float(i.shape[0])]}]
                for i in images
            ]

    parser._layout_recognizer = FakeLayout()
    _fake_fuse_page(parser)
    monkeypatch.setenv("DEEPDOC_RENDER_WINDOW_SIZE", "2")

    result = parser(_make_pdf(3), pdf_mode="full", chunk_size=200)
    assert result.metadata["pages"] == 3
    text_tags = [
        entry.get("position_tag") or entry.get("source_id")
        for entry in result.metadata["reading_order"]
        if entry["kind"] == "text"
    ]
    assert text_tags, "text entries 应携带 position_tag"
    pages = sorted({int(tag.split("\t")[0][2:]) for tag in text_tags if tag})
    assert pages == [1, 2, 3], f"分窗后 position_tag 页码必须为全书 1-based: {pages}"


def test_layout_unavailable_falls_back_to_heuristic_per_window(monkeypatch):
    """layout 不可用 → 全部窗走启发式，layout_source='heuristic'（回退可见）。"""
    import novamind.engines.document.integrations.deepdoc.parsers.pdf as pdf_mod

    parser = RAGFlowPdfParser()
    _fake_fuse_page(parser, char_text="heuristic")
    monkeypatch.setattr(
        pdf_mod,
        "get_vision_health_status",
        lambda: {"can_run_layout_inference": False, "can_run_vendored_ocr": True},
    )
    monkeypatch.setenv("DEEPDOC_RENDER_WINDOW_SIZE", "2")

    image_list, fused_pages, layout_pages, meta = parser._extract_fused_pages(_make_pdf(3))

    assert meta["layout_source"] == "heuristic"
    assert meta["layout_model_error"] is None
    assert len(layout_pages) == 3
    assert all(page for page in layout_pages), "启发式布局页不应为空"


def test_window_forward_failure_falls_back_for_that_window(monkeypatch):
    """窗内推理失败 → 该窗回退启发式，后续窗继续走 ONNX（按窗降级不整本扩散）。"""
    parser = RAGFlowPdfParser()
    _fake_fuse_page(parser)
    forward_calls: list[int] = []

    class FlakyLayout(LayoutRecognizer4YOLOv10):
        def __init__(self):
            self.loaded = True
            self.garbage_layouts = ["footer", "header", "reference"]
            self.center = True
            self.input_shape = (640, 640)
            self.label_list = self.labels

        def load(self):
            pass

        def ensure_loaded(self):
            pass

        def forward(self, images, thr=0.2, batch_size=16):
            forward_calls.append(len(images))
            if forward_calls:
                raise RuntimeError("onnx inference boom")
            return []

    parser._layout_recognizer = FlakyLayout()
    monkeypatch.setenv("DEEPDOC_RENDER_WINDOW_SIZE", "2")

    image_list, fused_pages, layout_pages, meta = parser._extract_fused_pages(_make_pdf(3))

    assert forward_calls == [2, 1], "失败后不应中断后续窗推理"
    assert meta["layout_source"] == "heuristic"
    assert meta["layout_model_error"] == "onnx inference boom"
    assert len(layout_pages) == 3
    assert all(page for page in layout_pages)
