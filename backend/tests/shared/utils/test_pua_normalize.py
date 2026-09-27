"""PUA 归一化共享模块的行为矩阵直测。

规则与三个解析出口（deepdoc full/plain、通用 reader）共用，
这里直接测 novamind.shared.utils.text_utils.pua_normalize 的行为矩阵。
"""
import pytest
from novamind.shared.utils.text_utils import (
    normalize_pua_text,
    replace_pua,
)
from novamind.shared.utils.text_utils.pua_normalize import PUA_CHAR_PATTERN

pytestmark = pytest.mark.unit

E5CE = ""  # doc583 填空栏占位
E5D2 = ""  # doc583 句读占位（前半）
E5CF = ""  # doc583 句读占位（后半）
E5E5 = ""  # doc583 全角空格占位


@pytest.mark.unit
def test_pua_pair_between_cjk_deleted():
    """成对句读占位夹在 CJK 字间 → 删除（穿透连续 PUA 判定邻居）。"""
    assert normalize_pua_text("研究成" + E5D2 + E5CF + "果") == "研究成果"
    assert normalize_pua_text("分类号" + E5CE + "密级") == "分类号密级"


@pytest.mark.unit
def test_pua_word_separator_keeps_space():
    """词间分隔占位（全角空格形态）→ 保空格防粘连。"""
    assert normalize_pua_text("Ｔｗｏ" + E5E5 + "Ｃｌａｓｓ") == "Ｔｗｏ Ｃｌａｓｓ"
    assert normalize_pua_text("Class" + E5E5 + "of") == "Class of"


@pytest.mark.unit
def test_fullwidth_ascii_not_cjk():
    """全角 ASCII（U+FF00-FF5E）不算 CJK——英文标题词间语境保空格。"""
    assert normalize_pua_text("Ｔｗｏ" + E5E5 + "Ｃｌａｓｓ") == "Ｔｗｏ Ｃｌａｓｓ"
    assert normalize_pua_text("２０１８年" + E5E5 + "４月") == "２０１８年 ４月"


@pytest.mark.unit
def test_trailing_pua_collapses_to_single_space():
    """行尾连续 PUA → 归一为单空格（出口收紧）。"""
    assert normalize_pua_text("成果" + E5D2 + E5CF) == "成果 "


@pytest.mark.unit
def test_empty_and_no_pua_passthrough():
    """空串与无 PUA 文本逐字不变（反例保障）。"""
    assert normalize_pua_text("") == ""
    assert normalize_pua_text("分类号１０３８４密级") == "分类号１０３８４密级"
    assert normalize_pua_text("两类低秩矩阵重构模型及其应用探索") == (
        "两类低秩矩阵重构模型及其应用探索"
    )


@pytest.mark.unit
def test_pattern_covers_pua_range():
    """区间正则命中 4 个实测码点，不命中普通中文/全角数字。"""
    for cp in (0xE5CE, 0xE5D2, 0xE5CF, 0xE5E5):
        assert PUA_CHAR_PATTERN.match(chr(cp))
    assert not PUA_CHAR_PATTERN.match("研")
    assert not PUA_CHAR_PATTERN.match("１")


@pytest.mark.unit
def test_replace_pua_is_re_sub_callback():
    """replace_pua 可独立用作 re.sub 回调（公共 API 契约）。"""
    import re

    out = re.sub(PUA_CHAR_PATTERN, replace_pua, "研" + E5CE + "究")
    assert out == "研究"
