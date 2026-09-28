"""PUA（Private Use Area，私用区）字符出口归一化。

deepdoc full/plain 两解析出口与通用 pdf_reader 页级出口共用同一语境化规则（normalize_pua_text），数学符号类 PUA 一并归一是安全退化方向。
"""
from __future__ import annotations

import re

# 低密度 PUA 占位字形的码位区间。
PUA_CHAR_PATTERN = re.compile("[\ue000-\uf8ff]")

# PUA 归一时的 CJK 语境判据：CJK 统一表意文字 + 扩展A + 兼容表意 + 全角
# 标点（U+FF5F-FFEF）。全角 ASCII（U+FF00-FF5E，Ｔｗｏ２０１８ 等）不算
# CJK——上游对拍实测它们出现在英文标题词间，PUA 是词间分隔形态，需保空格。
CJK_FULLWIDTH_PATTERN = re.compile(
    "[\u2e80-\u9fff\u3400-\u4dbf\uf900-\ufaff\uff5f-\uffef]"
)


def is_cjk_like(ch: str) -> bool:
    """判断字符是否属 CJK 语境（含扩展A、兼容表意、全角标点；全角 ASCII 不算）。"""
    return bool(CJK_FULLWIDTH_PATTERN.match(ch))


def replace_pua(match: re.Match) -> str:
    """PUA 占位字形的语境化替换（re.sub 回调）。

    邻居都是 CJK/全角 → 句读占位形态，删除（CJK 排版字间无空格，换空格会
    断词，doc583 实测「研究成<U+E5D2><U+E5CF>果」）；否则 → 词间分隔形态
    （当全角空格用，如英文标题「Ｔｗｏ<U+E5E5>Ｃｌａｓｓ」），替换为空格
    防词粘连。边界（行首/行尾/空邻居）按非 CJK 处理保空格。
    """
    s = match.string
    start, end = match.start(), match.end()
    # 邻居判定跳过连续 PUA（句读占位常成对出现，如 <U+E5D2><U+E5CF>）
    i = start - 1
    while i >= 0 and PUA_CHAR_PATTERN.match(s[i]):
        i -= 1
    prev_cjk = i >= 0 and is_cjk_like(s[i])
    j = end
    while j < len(s) and PUA_CHAR_PATTERN.match(s[j]):
        j += 1
    next_cjk = j < len(s) and is_cjk_like(s[j])
    if prev_cjk and next_cjk:
        return ""
    return " "


def normalize_pua_text(text: str) -> str:
    """文本出口归一：PUA 语境化替换 + 连续空格收紧。

    各解析路径（deepdoc full/plain、通用 reader）调用方一行接入的门面。
    """
    if not text:
        return text
    out = PUA_CHAR_PATTERN.sub(replace_pua, text)
    if "  " in out:
        out = re.sub(r" {2,}", " ", out)
    return out
