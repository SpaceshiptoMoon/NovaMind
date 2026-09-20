"""updown_concat GBK 乱码修复回归测试。

5c29484 曾把上游 UTF-8 中文正则按 GBK 误解码（绗琜闆朵竴=第一二三四），
导致：中文标题边界保护（_match_proj）永不命中、xgboost 31 特征中 9 个中文
标点特征恒 False、启发式路径句号永不 break——段落粘连成大块。本文件锁定
修复后的行为，防止再次回归。
"""
import pytest
from novamind.engines.document.integrations.deepdoc.parsers.pdf import DeepDocPdfBox
from novamind.engines.document.integrations.deepdoc.updown_concat import UpDownConcatMerger

pytestmark = pytest.mark.unit


def _box(page=1, top=0.0, bottom=10.0, text="", x0=0.0, x1=100.0, col_id=0, layout_type="text"):
    return DeepDocPdfBox(
        page=page, x0=x0, x1=x1, top=top, bottom=bottom, text=text,
        col_id=col_id, layout_type=layout_type,
    )


def _state(text, page=1, top=0.0, bottom=10.0, layout_type="text"):
    return {"text": text, "x0": 0.0, "x1": 100.0, "top": top, "bottom": bottom,
            "page_number": page, "layout_type": layout_type}


class TestMatchProj:
    """修复前 _match_proj 的模式全是乱码，中文标题 100% 漏检。"""

    @pytest.mark.parametrize("heading", [
        "第一章 引言",
        "第一条 总则",
        "（三）系统架构",
        "3.2.1 数据模型",
        "第十章 结论",
    ])
    def test_chinese_headings_match(self, heading):
        assert UpDownConcatMerger._match_proj(heading) is True

    @pytest.mark.parametrize("plain", [
        "普通正文内容段落",
        "这是一段没有编号的话",
    ])
    def test_plain_text_does_not_match(self, plain):
        assert UpDownConcatMerger._match_proj(plain) is False


class TestChinesePunctuationFeatures:
    """修复前 9 个中文标点特征恒 False，xgboost 模型输入系统性失真。"""

    def test_full_stop_feature_fires(self):
        up = _state("这句话结束了。")
        down = _state("新的一行开始", top=12.0, bottom=22.0)
        feats = UpDownConcatMerger()._updown_concat_features(up, down)
        # 特征 9：up 以 。？！；!?;)） 结尾
        assert feats[8] is True

    def test_comma_tail_feature_fires(self):
        up = _state("这里没有结束，")
        down = _state("接续的内容", top=12.0, bottom=22.0)
        feats = UpDownConcatMerger()._updown_concat_features(up, down)
        # 特征 10：up 以 ，：‘“、0-9（+- 结尾
        assert feats[9] is True

    def test_down_punctuation_feature_fires(self):
        up = _state("上一行正常结束")
        down = _state("。续行内容", top=12.0, bottom=22.0)
        feats = UpDownConcatMerger()._updown_concat_features(up, down)
        # 特征 11：down 以 。，；：’”？！》】）等开头
        assert feats[10] is True

    def test_clean_text_features_stay_false(self):
        up = _state("行尾没有标点")
        down = _state("行首没有标点", top=12.0, bottom=22.0)
        feats = UpDownConcatMerger()._updown_concat_features(up, down)
        assert feats[8] is False
        assert feats[9] is False
        assert feats[10] is False


class TestHeuristicMergePunctuation:
    """修复前启发式路径句号永不 break（乱码字符集），段落全粘连。"""

    def test_full_stop_breaks_paragraph(self):
        merger = UpDownConcatMerger()
        upper = _box(text="第一段结束。", bottom=10.0)
        lower = _box(text="第二段开始", top=14.0, bottom=24.0)
        assert merger._should_merge_heuristic(upper, lower, mean_height=10.0) is False

    def test_comma_continues_line(self):
        merger = UpDownConcatMerger()
        upper = _box(text="行尾逗号，", bottom=10.0)
        lower = _box(text="接续下一行", top=10.0, bottom=20.0)
        assert merger._should_merge_heuristic(upper, lower, mean_height=10.0) is True

    def test_plain_tight_lines_merge(self):
        """无标点、行距紧凑的相邻行（正常段落内部换行）应合并。"""
        merger = UpDownConcatMerger()
        upper = _box(text="段落的中间", bottom=10.0)
        lower = _box(text="换行继续", top=10.0, bottom=20.0)
        assert merger._should_merge_heuristic(upper, lower, mean_height=10.0) is True

    def test_heading_boundary_breaks_paragraph(self):
        """下一段以中文编号标题开头时应断段（_match_proj 修复后的效果）。"""
        merger = UpDownConcatMerger()
        upper = _box(text="上一段正文。", bottom=10.0)
        lower = _box(text="第二章 方法", top=10.0, bottom=20.0)
        assert merger._should_merge_heuristic(upper, lower, mean_height=10.0) is False


class TestPageNumberBoxCleanup:
    """上游 _naive_vertical_merge 的页码框清理移植：跨页边界纯页码框剔除。"""

    def _boxes(self):
        return [
            _box(page=1, top=100.0, bottom=110.0, text="正文最后一段"),
            _box(page=1, top=120.0, bottom=130.0, text="- 12 -"),
            _box(page=2, top=0.0, bottom=10.0, text="下一页正文"),
            _box(page=2, top=20.0, bottom=30.0, text="13"),
            _box(page=3, top=0.0, bottom=10.0, text="第三页正文"),
        ]

    def test_page_number_boxes_dropped(self):
        kept = UpDownConcatMerger()._drop_page_number_boxes(self._boxes())
        texts = [b.text for b in kept]
        assert "- 12 -" not in texts
        assert "13" not in texts
        assert "正文最后一段" in texts and "下一页正文" in texts and "第三页正文" in texts

    def test_body_numbers_not_dropped(self):
        """页中间的数字框（非跨页边界）不应被误删。"""
        boxes = [
            _box(page=1, top=0.0, bottom=10.0, text="2026 年数据"),
            _box(page=2, top=0.0, bottom=10.0, text="下一页"),
        ]
        kept = UpDownConcatMerger()._drop_page_number_boxes(boxes)
        assert len(kept) == 2

    def test_merge_entry_point_applies_cleanup(self):
        """merge() 入口应先做页码清理（无模型环境走 heuristic 路径一并验证）。"""
        merger = UpDownConcatMerger()
        merged, strategy = merger.merge(self._boxes())
        texts = [b.text for b in merged]
        assert "- 12 -" not in texts
        assert strategy in {"heuristic", "xgboost"}