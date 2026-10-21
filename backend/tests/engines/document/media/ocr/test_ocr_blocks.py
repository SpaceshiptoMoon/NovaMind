"""OcrBlock/OcrResult 中间表示与 Markdown 渲染的单元测试。"""
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.engines.document.media.ocr.blocks import (
    OcrBlock,
    OcrResult,
    bbox_from_quad,
)


def _block(
    block_type: str = "text",
    page_num: int = 0,
    bbox: tuple[float, float, float, float] | None = None,
    text: str = "",
    markdown: str = "",
) -> OcrBlock:
    return OcrBlock(
        block_type=block_type, page_num=page_num, bbox=bbox, text=text, markdown=markdown
    )


class TestBboxFromQuad:
    def test_four_corners_min_max(self):
        quad = [{"x": 770, "y": 292}, {"x": 613, "y": 332}, {"x": 613, "y": 292}, {"x": 770, "y": 332}]
        assert bbox_from_quad(quad) == (613.0, 292.0, 770.0, 332.0)

    def test_malformed_returns_none(self):
        # 缺角 / 非 dict 元素 / 坐标缺失 / 非数值——全部返回 None 不抛
        assert bbox_from_quad([]) is None
        assert bbox_from_quad(None) is None
        assert bbox_from_quad([{"x": 1, "y": 2}, "bad", {"x": 3, "y": 4}]) is None
        assert bbox_from_quad([{"x": 1, "y": 2}, {"x": 3}]) is None
        assert bbox_from_quad([{"x": "a", "y": 2}, {"x": 3, "y": 4}]) is None


class TestRenderMarkdown:
    def test_orders_by_page_then_y(self):
        result = OcrResult(
            blocks=[
                _block(page_num=1, bbox=(0, 500, 10, 510), text="第二页下"),
                _block(page_num=0, bbox=(0, 100, 10, 110), text="第一页下"),
                _block(page_num=0, bbox=(0, 10, 10, 20), text="第一页上"),
                _block(page_num=1, bbox=(0, 10, 10, 20), text="第二页上"),
            ]
        )
        md = result.render_markdown()
        assert md == "第一页上\n\n第一页下\n\n第二页上\n\n第二页下"

    def test_title_formula_text_styles(self):
        result = OcrResult(
            blocks=[
                _block(block_type="title", text="iDLHCG"),
                _block(block_type="formula", text="\\langle g_k, d_k \\rangle < 0"),
                _block(block_type="formula", text="$$x_{k+1} = T(x_k)$$"),
                _block(text="正文段落"),
            ]
        )
        md = result.render_markdown()
        assert "# iDLHCG" in md
        assert "$$\n\\langle g_k, d_k \\rangle < 0\n$$" in md
        # 已含 $$ 的 formula 原样保留不二次包裹
        assert "$$x_{k+1} = T(x_k)$$" in md
        assert "正文段落" in md

    def test_markdown_native_markers_not_doubled(self):
        """供应商 markdownContent 自带的 # / $ 标记不得二次叠加。"""
        result = OcrResult(
            blocks=[
                _block(block_type="title", markdown="# 第一章 绪论"),
                _block(block_type="title", markdown="## 1.1 背景"),
                _block(block_type="formula", markdown="$E = mc^2$"),
                _block(block_type="formula", markdown="$$\na^2 + b^2 = c^2\n$$"),
            ]
        )
        md = result.render_markdown()
        assert "# 第一章 绪论" in md
        assert "# # " not in md
        assert "## 1.1 背景" in md
        assert "$E = mc^2$" in md
        assert "$$\n$E = mc^2$\n$$" not in md
        assert md.count("$$\na^2 + b^2 = c^2\n$$") == 1

    def test_prefers_markdown_over_text(self):
        result = OcrResult(blocks=[_block(text="纯文本", markdown="**markdown 版**")])
        assert result.render_markdown() == "**markdown 版**"

    def test_drops_empty_blocks(self):
        result = OcrResult(
            blocks=[
                _block(text=""),
                _block(markdown="  "),
                _block(text="有内容"),
                _block(text="   ", markdown=""),
            ]
        )
        assert result.render_markdown() == "有内容"

    def test_bbox_none_sinks_after_positioned(self):
        # 无 bbox 的块排在同页有 bbox 块之后（页内按原相对顺序稳定）
        result = OcrResult(
            blocks=[
                _block(page_num=0, bbox=None, text="无坐标甲"),
                _block(page_num=0, bbox=(0, 50, 10, 60), text="有坐标"),
                _block(page_num=0, bbox=None, text="无坐标乙"),
            ]
        )
        assert result.render_markdown() == "有坐标\n\n无坐标甲\n\n无坐标乙"


class TestOcrResultMeta:
    def test_defaults(self):
        result = OcrResult(blocks=[])
        assert result.page_count == 1
        assert result.model == ""
        assert result.protocol == ""
        assert result.render_markdown() == ""


@pytest.mark.parametrize(
    "kwargs",
    [
        {"block_type": "unknown_kind", "page_num": 0, "text": "x"},
        {"block_type": "text", "page_num": -1, "text": "x"},
    ],
)
def test_block_tolerates_odd_fields(kwargs):
    # 中间表示不自行清洗字段——清洗是各通路归一逻辑的职责（见 qwen.py 测试）
    block = OcrBlock(**kwargs)
    assert block.preferred_text() == "x"
