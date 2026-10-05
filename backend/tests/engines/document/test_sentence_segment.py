"""公共切句函数测试：句读边界 + 不丢字符 + 超长硬切。

验证核心不变量：
1. 句读保留：中英文句读（。！？!? 与后随空白的 .）随前句尾部保留；
2. 数字保护：小数点/版本号（3.14、v1.2）不在句点处误切；
3. 无标点段：整段成为单句，绝不静默丢弃；
4. 超长硬切：超过 max_sentence_length 的句按固定窗口切分且内容无丢失；
5. 纯空白输入返回空列表。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.splitters.sentence_segment import split_sentences

pytestmark = pytest.mark.unit


class TestSentenceBoundaries:
    def test_zh_en_boundary_keeps_punctuation(self):
        """正例：中英文句读切分且句读保留在前句尾部。"""
        sentences = split_sentences("甲句。乙句！Third. Fourth?")
        assert sentences == ["甲句。", "乙句！", "Third.", "Fourth?"]

    def test_decimal_and_version_not_split(self):
        """数字保护：3.14 / v1.2 的句点后无空白，不切。"""
        sentences = split_sentences("版本3.14与v1.2发布。下一句。")
        assert sentences == ["版本3.14与v1.2发布。", "下一句。"]

    def test_english_period_requires_following_space(self):
        """英文句点仅后随空白才断：'e.g. x' 在 'e.g.' 后断是既有实现同级容忍，
        但 'x.y'（无空白）绝不断。"""
        sentences = split_sentences("path.to.file 及后续。")
        assert sentences == ["path.to.file 及后续。"]

    def test_final_sentence_without_punctuation_kept(self):
        """结尾无句读的尾句保留（零宽断言 split 的尾段不丢）。"""
        sentences = split_sentences("第一句。没有句读的尾巴")
        assert sentences == ["第一句。", "没有句读的尾巴"]


class TestNoPunctuationParagraph:
    def test_no_punctuation_paragraph_single_sentence(self):
        """无标点长段（代码块/URL/base64 场景）整段成为单句不丢字符。"""
        text = "https://example.com/very/long/path?q=1&w=2 完全没有句读的段落"
        assert split_sentences(text) == [text]


class TestOversizeSentence:
    def test_oversize_sentence_hard_split_no_loss(self):
        """超长句硬切：各片 <= 上限且 strip 拼接还原原文。"""
        long_sentence = "长" * 2500
        sentences = split_sentences(long_sentence, max_sentence_length=1000)
        assert all(len(s) <= 1000 for s in sentences)
        assert "".join(sentences) == long_sentence

    def test_oversize_sentence_with_punctuation(self):
        """超长句带句读：先按句读切，无标点残余部分再硬切，拼接还原。"""
        text = "首句。" + "中" * 1500 + "。"
        sentences = split_sentences(text, max_sentence_length=1000)
        assert sentences[0] == "首句。"
        assert "".join(s.strip() for s in sentences) == text


class TestEdgeCases:
    def test_empty_and_whitespace_input(self):
        """反例：空串与纯空白输入返回空列表。"""
        assert split_sentences("") == []
        assert split_sentences("   \n\t  ") == []

    def test_single_short_sentence(self):
        """单短句原样返回（无切分动作）。"""
        assert split_sentences("好。") == ["好。"]
