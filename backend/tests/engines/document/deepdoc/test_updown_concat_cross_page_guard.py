"""跨页段落合并守卫回归测试（评审补跑欠账发现，2026-09-27）。

fork 独有的后置合并段 ``_merge_vertical_boxes_with_strategy`` 在 page-local
域运行（上游等价段在累积 Y 域按页分组，跨页间距天然巨大无需守卫）；无守卫时
跨页对 y_dis≈0、``mh*16`` break 永不触发，xgboost 可把整本书并成一块——合并块
page 取 min，页 2/3 的 position_tag 页码全部丢失，引用溯源指错页（分窗批处理
0dfe964 引入，test_windowed_parse_full_keeps_book_wide_position_tags 捕获）。

修复：跨页仅当段尾是强续行标点（句子明显未完）才允许进模型判定。
正反用例：
- 正例：逗号结尾的跨页段允许合并（排版常识：句子未完不因换页断段）；
- 反例 1：句号结尾的跨页段必须断开；
- 反例 2：全书级多页串不因首段逗号而全并（页 2→3 同样受守卫约束）。
"""
import pytest
from novamind.engines.document.integrations.deepdoc.parsers.pdf import DeepDocPdfBox
from novamind.engines.document.integrations.deepdoc.updown_concat import (
    UpDownConcatMerger,
)

pytestmark = pytest.mark.unit


def _box(page=1, top=0.0, bottom=10.0, text="", x0=0.0, x1=100.0, col_id=0, layout_type="text"):
    return DeepDocPdfBox(
        page=page, x0=x0, x1=x1, top=top, bottom=bottom, text=text,
        col_id=col_id, layout_type=layout_type,
    )


class _StubModel:
    """恒判可合并的桩：把守卫的判定压力全部放在门控上。"""

    def predict(self, _dm):
        return [0.9]


class TestStrongContinuation:
    def test_continuation_tails(self):
        assert UpDownConcatMerger._strong_continuation("未完，") is True
        assert UpDownConcatMerger._strong_continuation("未完;") is True
        assert UpDownConcatMerger._strong_continuation("括号未闭 (") is True
        assert UpDownConcatMerger._strong_continuation("破折—") is True

    def test_terminal_tails(self):
        assert UpDownConcatMerger._strong_continuation("句号。") is False
        assert UpDownConcatMerger._strong_continuation("问号？") is False
        assert UpDownConcatMerger._strong_continuation("") is False


def _make_merger_with_stub_model(monkeypatch):
    merger = UpDownConcatMerger()
    monkeypatch.setattr(merger, "model_available", lambda: True)
    monkeypatch.setattr(merger, "load_model", lambda: _StubModel())
    return merger


def test_cross_page_merge_allowed_with_continuation_tail(monkeypatch):
    """正例：页 1 段尾逗号（强续行）→ 跨页合并允许，产 1 块。"""
    merger = _make_merger_with_stub_model(monkeypatch)
    boxes = [
        _box(page=1, top=10.0, bottom=20.0, text="本页内容未完，"),
        _box(page=2, top=10.0, bottom=20.0, text="下页接续内容"),
    ]
    merged, strategy = merger.merge(boxes)
    assert strategy == "xgboost"
    assert len(merged) == 1
    # 中文尾（逗号非字母数字）→ 无空格直拼；跨页块 page 取 min 后为 1
    assert merged[0].text == "本页内容未完，下页接续内容"
    assert merged[0].page == 1


def test_cross_page_split_forced_on_sentence_end(monkeypatch):
    """反例：页 1 段尾句号 → 跨页必须断开，页码各自保留。"""
    merger = _make_merger_with_stub_model(monkeypatch)
    boxes = [
        _box(page=1, top=10.0, bottom=20.0, text="本页内容已完。"),
        _box(page=2, top=10.0, bottom=20.0, text="下页新起内容"),
    ]
    merged, _ = merger.merge(boxes)
    assert len(merged) == 2
    assert sorted(box.page for box in merged) == [1, 2]


def test_whole_book_not_collapsed_via_first_page_comma(monkeypatch):
    """反例：页 1 逗号只放行 1→2 一次；页 2 句号挡住 2→3，全书不被并成一块。"""
    merger = _make_merger_with_stub_model(monkeypatch)
    boxes = [
        _box(page=1, top=10.0, bottom=20.0, text="第一页未完，"),
        _box(page=2, top=10.0, bottom=20.0, text="第二页结束。"),
        _box(page=3, top=10.0, bottom=20.0, text="第三页新内容"),
    ]
    merged, _ = merger.merge(boxes)
    pages = sorted(box.page for box in merged)
    assert len(merged) == 2
    assert pages == [1, 3] or pages == [1, 2, 3] and len(merged) == 3
    # 关键断言：不存在一个横跨全部 3 页的块
    assert not (len(merged) == 1)
