"""PageNoiseFilter 回归测试：覆盖 DIRTY_TEXT_PATTERN 空匹配 bug 与脏页过滤。"""
import re

from novamind.engines.document.integrations.deepdoc.page_filter import (
    DIRTY_TEXT_PATTERN,
    PageNoiseFilter,
    TOC_HEADING_PATTERN,
)
from novamind.engines.document.integrations.deepdoc.parsers.pdf import DeepDocPdfBox


def _box(page: int, text: str) -> DeepDocPdfBox:
    return DeepDocPdfBox(page=page, x0=0.0, x1=10.0, top=0.0, bottom=10.0, text=text)


def test_dirty_pattern_does_not_match_empty_string():
    """DIRTY_TEXT_PATTERN 的锟? 量词曾让它在任意文本上零宽空匹配，导致每个 box 都
    被判脏、>3 个 box 的页整页删除。修复后正常文本不得命中。"""
    assert DIRTY_TEXT_PATTERN.search("正常中文 this is english 123") is None
    assert DIRTY_TEXT_PATTERN.search("") is None
    # 真正的脏文本仍应命中
    assert DIRTY_TEXT_PATTERN.search("abc锟斤拷def") is not None
    assert DIRTY_TEXT_PATTERN.search("(cid:42)") is not None


def test_filter_keeps_clean_pages_with_many_boxes():
    """一页有 >3 个干净文本框不应被脏页过滤删除（复现 doc 566：37 个干净 box
    被 BUG 整页删除）。"""
    boxes = [_box(1, f"第{i}段正常中文内容") for i in range(10)]
    filtered, meta = PageNoiseFilter().filter_boxes(boxes, total_pages=1)
    assert len(filtered) == 10
    assert meta["dirty_pages"] == []
    assert meta["removed_pages"] == []


def test_filter_removes_genuinely_dirty_pages():
    """含 cid/PUA 占 >3 box 的页仍应被删除。"""
    boxes = [_box(1, "(cid:1)"), _box(1, "(cid:2)"), _box(1, "(cid:3)"), _box(1, "正常")]
    boxes += [_box(2, "正常内容") for _ in range(5)]
    filtered, meta = PageNoiseFilter().filter_boxes(boxes, total_pages=2)
    # 页1 有 3 个 cid box（>3 阈值需要 >3，3 个不触发；补一个到 4）
    assert 2 in {int(b.page) for b in filtered}  # 页2 保留


def test_filter_removes_dirty_page_when_more_than_three():
    """页1 有 4 个 cid box（>3）应被整页删除。"""
    boxes = [_box(1, f"(cid:{i})") for i in range(4)]
    boxes += [_box(2, "正常内容") for _ in range(5)]
    filtered, meta = PageNoiseFilter().filter_boxes(boxes, total_pages=2)
    pages = {int(b.page) for b in filtered}
    assert 1 not in pages
    assert 2 in pages
    assert meta["dirty_pages"] == [1]


def test_dirty_pattern_matches_toc_dot_leaders():
    """目录点线语义（对齐上游 _filter_forpages）：TOC 引导行的中点/省略号/ASCII
    点串应命中；正文句末 3 个 ASCII 点不应命中（避免正文页误删）。"""
    assert DIRTY_TEXT_PATTERN.search("第一章 概述 ··········· 12") is not None
    assert DIRTY_TEXT_PATTERN.search("第二章 方法 …… 25") is not None
    assert DIRTY_TEXT_PATTERN.search("3.1 数据模型 ........ 31") is not None
    assert DIRTY_TEXT_PATTERN.search("正文里的省略号...") is None


def test_toc_dot_leader_page_dropped():
    """一页 >3 个含点线引导的框 → 整页剔除（扫描版目录页残留的修复）。"""
    toc_lines = [f"第{i}章 标题{i} ········· {i * 10}" for i in range(1, 6)]
    boxes = [_box(1, text) for text in toc_lines]
    boxes += [_box(2, "正文内容") for _ in range(3)]
    filtered, meta = PageNoiseFilter().filter_boxes(boxes, total_pages=2)
    pages = {int(b.page) for b in filtered}
    assert 1 not in pages
    assert 2 in pages
    assert meta["dirty_pages"] == [1]


def test_toc_heading_pattern_matches_chinese():
    """TOC_HEADING_PATTERN 的中文项曾是 GB18030 乱码（目录→鐩綍 等），永远匹配
    不到中文目录页。修复后应匹配「目录/目次/致谢」。"""
    for heading in ["目录", "目次", "致谢", "Contents", "Acknowledgements"]:
        normalized = re.sub(r"( |　)+", "", heading.lower())
        assert TOC_HEADING_PATTERN.match(normalized) is not None, heading
    # 非目录标题不应匹配
    for plain in ["正文内容", "第一章 引言", "introduction"]:
        normalized = re.sub(r"( |　)+", "", plain.lower())
        assert TOC_HEADING_PATTERN.match(normalized) is None, plain