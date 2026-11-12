"""合并块 position_tag 重算回归测试（跨页并块残余修复，2026-11-12）。

回归背景：``_merge_block_states`` / ``_heuristic_merge`` 合并循环从不改写
position_tag——同页合并后 tag 停留首片段行，引用溯源高亮只覆盖段落首行；
跨页并块（守卫放行的强续行）tag 同样停留首片段。修复语义：
- 同页合并：按最终 bbox 重算跨度 tag（对齐 pdf.py _boxes_from_vendored_domain
  合并后重算先例），高亮覆盖整段；
- 跨页合并：保留首片段 tag——坐标是页局部系，跨页造 span 会在首页产生
  错位巨矩形（指错页的历史教训见 test_windowed_parse_full_keeps_book_wide_position_tags）。
"""
import pytest
from novamind.engines.document.integrations.deepdoc.parsers.pdf import DeepDocPdfBox
from novamind.engines.document.integrations.deepdoc.updown_concat import (
    UpDownConcatMerger,
)

pytestmark = pytest.mark.unit


def _box(page=1, top=0.0, bottom=10.0, text="", x0=0.0, x1=100.0, col_id=0,
         layout_type="text", position_tag=""):
    return DeepDocPdfBox(
        page=page, x0=x0, x1=x1, top=top, bottom=bottom, text=text,
        col_id=col_id, layout_type=layout_type, position_tag=position_tag,
    )


class _StubModel:
    def predict(self, _dm):
        return [0.9]


def _make_xgb_merger(monkeypatch):
    merger = UpDownConcatMerger()
    monkeypatch.setattr(merger, "model_available", lambda: True)
    monkeypatch.setattr(merger, "load_model", lambda: _StubModel())
    return merger


def test_same_page_merge_respans_position_tag(monkeypatch):
    """正例（xgb 路径）：同页两行合并 → tag 重算为跨度 bbox（高亮覆盖整段）。"""
    merger = _make_xgb_merger(monkeypatch)
    boxes = [
        _box(page=1, top=10.0, bottom=20.0, x0=10.0, x1=90.0, text="上半句未完，",
             position_tag="@@1\t10.0\t90.0\t10.0\t20.0##"),
        _box(page=1, top=21.0, bottom=40.0, x0=0.0, x1=100.0, text="下半句内容",
             position_tag="@@1\t0.0\t100.0\t21.0\t40.0##"),
    ]
    merged, strategy = merger.merge(boxes)
    assert strategy == "xgboost"
    assert len(merged) == 1
    # 跨度：x0 取 min、x1 取 max、top 取首行、bottom 取末行
    assert merged[0].position_tag == "@@1\t0.0\t100.0\t10.0\t40.0##"


def test_cross_page_merge_keeps_first_fragment_tag(monkeypatch):
    """反例（xgb 路径）：强续行放行的跨页并块 → tag 保留首片段（页局部系约束）。"""
    merger = _make_xgb_merger(monkeypatch)
    boxes = [
        _box(page=1, top=10.0, bottom=20.0, x0=0.0, x1=100.0, text="本页未完，",
             position_tag="@@1\t0.0\t100.0\t10.0\t20.0##"),
        _box(page=2, top=15.0, bottom=25.0, x0=0.0, x1=80.0, text="下页接续",
             position_tag="@@2\t0.0\t80.0\t15.0\t25.0##"),
    ]
    merged, _ = merger.merge(boxes)
    assert len(merged) == 1
    assert merged[0].page == 1
    # 不重算跨度（bottom=25 属页 2，跨页 span 会指错几何）；保留首片段原 tag
    assert merged[0].position_tag == "@@1\t0.0\t100.0\t10.0\t20.0##"


def test_heuristic_same_page_merge_respans_position_tag(monkeypatch):
    """正例（heuristic 路径）：模型不可用走启发式，同页合并同样重算跨度 tag。"""
    merger = UpDownConcatMerger()
    # 本机装有 xgb 模型，须显式断开走 heuristic 回退（两条路径语义要求一致）
    monkeypatch.setattr(merger, "model_available", lambda: False)
    boxes = [
        _box(page=1, top=10.0, bottom=20.0, text="上半句未完，",
             position_tag="@@1\t0.0\t100.0\t10.0\t20.0##"),
        _box(page=1, top=21.0, bottom=31.0, text="下半句内容",
             position_tag="@@1\t0.0\t100.0\t21.0\t31.0##"),
    ]
    merged, strategy = merger.merge(boxes)
    assert strategy == "heuristic"
    assert len(merged) == 1
    assert merged[0].position_tag == "@@1\t0.0\t100.0\t10.0\t31.0##"


def test_unmerged_single_box_tag_untouched(monkeypatch):
    """相邻正常场景不误伤：句号结尾跨页不合并，两框各自 tag 原样保留。"""
    merger = _make_xgb_merger(monkeypatch)
    boxes = [
        _box(page=1, top=10.0, bottom=20.0, text="本页已完。",
             position_tag="@@1\t0.0\t100.0\t10.0\t20.0##"),
        _box(page=2, top=15.0, bottom=25.0, text="下页新起",
             position_tag="@@2\t0.0\t80.0\t15.0\t25.0##"),
    ]
    merged, _ = merger.merge(boxes)
    assert len(merged) == 2
    assert merged[0].position_tag == "@@1\t0.0\t100.0\t10.0\t20.0##"
    assert merged[1].position_tag == "@@2\t0.0\t80.0\t15.0\t25.0##"
