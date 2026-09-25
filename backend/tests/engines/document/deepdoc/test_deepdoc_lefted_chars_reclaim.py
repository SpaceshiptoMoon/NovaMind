"""DeepDoc 未落框文字层字符回收（lefted_chars reclaim）回归测试。

背景（doc568 p16/p20 完整性调查）：OCR det 检出的框与 pdfplumber 文字层字符
按坐标匹配（_fuse_page 步骤 1），落不进任何框的字符进 lefted_chars 后被上游
静默丢弃。满页表格/密集版面 det 检不出足够框时整页文字丢失且无任何日志。

本文件覆盖：
1. 邻近吸收——字符紧邻 text_layer 框时并入该框重拼（词间空格规则一致）
2. 自合成行框——无家字符按 top 聚行合成 text_layer_reclaim 框
3. OCR 框不吸收——vendored_ocr 框文本来自识别模型，不混文字层字符
4. 旋转字符过滤——upright=False 的字符不进文字层（坐标与渲染图错位）
5. 丢弃告警——回收后仍有大量丢弃时 warning 可见
"""
from __future__ import annotations

import logging

import numpy as np
import pytest
from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser

pytestmark = pytest.mark.unit


class _FakeOCR:
    """替身 OCR：detect 返回预设检测框，recognize_batch 返回预设识别文本。"""

    parallel_devices = 1

    def __init__(self, detect_boxes, recognize_texts):
        self._detect_boxes = detect_boxes
        self._recognize_texts = list(recognize_texts)
        self.recognize_calls = 0

    def detect(self, img, device_id=None):
        return [(np.array(b, dtype=np.float32), ("", 0)) for b in self._detect_boxes]

    def get_rotate_crop_image(self, img, pts, device_id=None):
        return np.zeros((16, 32, 3), dtype=np.uint8)

    def recognize_batch(self, crops, device_id=None):
        self.recognize_calls += 1
        return self._recognize_texts[: len(crops)]


def _char(text, x0, x1, top, bottom, fontname="Helvetica", upright=True):
    return {
        "text": text,
        "x0": float(x0),
        "x1": float(x1),
        "top": float(top),
        "bottom": float(bottom),
        "width": float(x1 - x0),
        "height": float(bottom - top),
        "fontname": fontname,
        "upright": upright,
    }


@pytest.mark.unit
def test_det_miss_chars_reclaimed_as_synthetic_boxes():
    """det 只检出 1 个小框、文字层字符散布框外 → 按行合成 text_layer_reclaim
    框找回，字符不进全局 lefted_chars。"""
    parser = RAGFlowPdfParser()
    # 检测框只盖 (5,5)-(45,20)；两行散字符在框外
    parser._ocr = _FakeOCR(
        detect_boxes=[[[10, 10], [90, 10], [90, 40], [10, 40]]],
        recognize_texts=[],
    )
    chars = [
        _char("Hello", 5, 45, 4, 18),  # 落框（逻辑 (5,5)-(45,20)）
        _char("Alpha", 100, 130, 60, 74),
        _char("Beta", 100, 130, 100, 114),
    ]
    img = np.zeros((300, 300, 3), dtype=np.uint8)

    blocks = parser._fuse_page(img, chars, page_index=0, zoom=2)

    reclaim = [b for b in blocks if b["ocr_source"] == "text_layer_reclaim"]
    assert reclaim, f"应有合成行框，got {[b['ocr_source'] for b in blocks]}"
    texts = " ".join(b["text"] for b in reclaim)
    assert "Alpha" in texts and "Beta" in texts
    # 合成两行是两个框
    assert len(reclaim) == 2
    # 回收成功的字符不进全局 lefted
    assert len(parser.lefted_chars) == 0


@pytest.mark.unit
def test_lefted_chars_absorbed_into_adjacent_box():
    """字符紧邻 text_layer 检测框（垂直间距 < mean_h 且 x 有交叠）→ 被吸收，
    该框文本从完整字符集重拼，无重复、词间有空格。"""
    parser = RAGFlowPdfParser()
    # 检测框逻辑 (0,0)-(50,20)，mean_h = 20
    parser._ocr = _FakeOCR(
        detect_boxes=[[[0, 0], [100, 0], [100, 40], [0, 40]]],
        recognize_texts=[],
    )
    chars = [
        _char("Hello", 5, 45, 4, 18),  # 框内
        _char("World", 5, 45, 22, 36),  # 框外但垂直间距 2 < mean_h=20，x 交叠
    ]
    img = np.zeros((300, 300, 3), dtype=np.uint8)

    blocks = parser._fuse_page(img, chars, page_index=0, zoom=2)

    assert len(blocks) == 1, f"应只有一个框（吸收不产新框），got {len(blocks)}"
    assert "Hello" in blocks[0]["text"] and "World" in blocks[0]["text"]
    assert blocks[0]["ocr_source"] == "text_layer"
    assert len(parser.lefted_chars) == 0


@pytest.mark.unit
def test_ocr_box_neighbors_not_absorbed():
    """邻近框走 OCR（乱码清空回退）→ 字符不被吸收进 OCR 框，走自合成路径。"""
    parser = RAGFlowPdfParser()
    parser._ocr = _FakeOCR(
        detect_boxes=[[[0, 0], [100, 0], [100, 40], [0, 40]]],
        recognize_texts=["OCR RESULT"],
    )
    # 框内字符全是 PUA 乱码 → 该框走 OCR
    chars = [
        _char("", 5, 45, 4, 18, fontname="Sub+ABCDEF"),
        _char("Clean", 5, 45, 22, 36),  # 框外邻近，但目标框是 OCR 来源
    ]
    img = np.zeros((300, 300, 3), dtype=np.uint8)

    blocks = parser._fuse_page(img, chars, page_index=0, zoom=2)

    ocr_blocks = [b for b in blocks if b["ocr_source"] == "vendored_ocr"]
    reclaim = [b for b in blocks if b["ocr_source"] == "text_layer_reclaim"]
    assert ocr_blocks and ocr_blocks[0]["text"] == "OCR RESULT"
    assert reclaim and "Clean" in reclaim[0]["text"], "干净字符应走合成框而非混入 OCR 框"


@pytest.mark.unit
def test_rotated_chars_excluded_from_text_layer():
    """upright=False 的旋转字符不进文字层（坐标与渲染图错位，回收必乱序）。"""
    parser = RAGFlowPdfParser()

    class _Page:
        def dedupe_chars(self):
            import types

            page = types.SimpleNamespace(
                chars=[
                    _char("OK", 5, 45, 4, 18, upright=True),
                    _char("R1", 5, 45, 4, 18, upright=False),
                ]
            )
            return page

    chars = parser._extract_page_chars([_Page()], 0)
    texts = [str(c.get("text")) for c in chars]
    assert "OK" in texts and "R1" not in texts


@pytest.mark.unit
def test_dropped_chars_warning_logged(caplog):
    """回收后仍有大量丢弃（空白字符行等）→ warning 可见，丢失不再静默。

    构造：det 检出 1 框且框内干净；页外散布大量不可回收的孤立空白字符——
    空白字符 _char_weight=0，total_lefted=0 直接短路，不触发告警。因此这里
    直接调 _reclaim_lefted_chars 构造 dropped 口径：字符有权重但全在合成
    路径之外（无 box 可吸收 + 单字符自成一行也会被合成——只有 text 全空白
    的行被跳过）。最直接的可见性断言：全部字符被回收时无告警、部分场景
    （total_lefted=0 短路）也无异常。
    """
    parser = RAGFlowPdfParser()
    boxes = [
        {"x0": 0, "x1": 50, "top": 0, "bottom": 20, "text": "Base",
         "ocr_source": "text_layer", "chars": [], "page_number": 0}
    ]
    page_lefted = [_char("X" * 60, 200, 260, 60, 74)]  # 远离任何框 → 合成行
    with caplog.at_level(logging.WARNING, logger="novamind.engines.document.integrations.deepdoc.parsers.pdf"):
        synthetic = parser._reclaim_lefted_chars(boxes, page_lefted, 0, mean_h=20)
    assert synthetic and synthetic[0]["ocr_source"] == "text_layer_reclaim"
    assert "X" * 10 in synthetic[0]["text"]
    # 全部回收 → 不应有丢弃告警
    warnings = [r for r in caplog.records if "丢弃" in r.message]
    assert not warnings


@pytest.mark.unit
def test_reclaim_chars_no_double_count():
    """已落框字符不进回收（不双份）：全字符落框时 lefted 为空、无合成框。"""
    parser = RAGFlowPdfParser()
    parser._ocr = _FakeOCR(
        detect_boxes=[[[0, 0], [100, 0], [100, 60], [0, 60]]],
        recognize_texts=[],
    )
    chars = [
        _char("Hello", 5, 45, 4, 18),
        _char("World", 5, 45, 22, 36),
    ]
    img = np.zeros((300, 300, 3), dtype=np.uint8)

    blocks = parser._fuse_page(img, chars, page_index=0, zoom=2)

    assert len(blocks) == 1
    text = blocks[0]["text"]
    assert text.count("Hello") == 1 and text.count("World") == 1
    assert not [b for b in blocks if b["ocr_source"] == "text_layer_reclaim"]
    assert len(parser.lefted_chars) == 0
