"""SimpleTokenizer 全半角归一（Q2B）回归测试。

回归背景：tokenize 正则 ``[A-Za-z0-9_]+|[\u4e00-\u9fff]+`` 只匹配半角 ASCII
与 CJK，全角字符（ＡＢＣ１２３、Ｔｗｏ２０１８Ｃｌａｓｓ 等，U+FF01-FF5E）
两个分支都不命中——整体丢出 token 流。后果：txt/html 切分的 token 计数偏小
→ 块超预算、html 超大块（纯全角 atom token 数为 0）永远切不开；docx 表格
单元格分类与段落合并特征同步失真。

修复：tokenize 入口先 strQ2B（对齐上游 RagTokenizer.tokenize 第一步，原本
已是死代码），只转计量输入不改存储文本。
"""
import pytest
from novamind.engines.document.integrations.deepdoc.compat import (
    num_tokens_from_string,
    rag_tokenizer,
)

pytestmark = pytest.mark.unit


def test_fullwidth_ascii_yields_tokens():
    """正例：全角字母数字串产出 token（修复前为 0），且与半角等价。"""
    fullwidth = "ＡＢＣ１２３"
    assert rag_tokenizer.tokenize(fullwidth) == "ABC123"
    assert num_tokens_from_string(fullwidth) == 1
    # 全角与对应半角的 token 流逐字节一致（计量等价性）
    assert rag_tokenizer.tokenize(fullwidth) == rag_tokenizer.tokenize("ABC123")


def test_halfwidth_ascii_unchanged():
    """相邻正常场景不误伤：纯半角输入与归一前逐字节一致（no-op）。"""
    samples = ["hello world", "Two2018Class v2.0", "foo_bar 123", ""]
    for text in samples:
        assert rag_tokenizer.tokenize(text) == " ".join(
            __import__("re").findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text)
        )


def test_fullwidth_punct_and_ideographic_space_normalized():
    """全角标点转半角、全角空格 U+3000 转普通空格（词边界恢复）。"""
    # ＋ 是全角（FF0B → +），正则不收 +，两侧数字串各成一个 token
    assert rag_tokenizer.tokenize("１２３＋４５６") == "123 456"
    # 全角空格分隔的两个全角 ASCII 词
    assert rag_tokenizer.tokenize("ａｂｃ　ｄｅｆ").split() == ["abc", "def"]


def test_mixed_cjk_fullwidth_counts():
    """全角+CJK 混排 token 计数与预期一致（切分预算不再失真）。"""
    # 全角字母 1 token + CJK 连串 1 token = 2
    assert num_tokens_from_string("Ｔｗｏ数据处理") == 2


def test_tag_consumes_normalized_tokens():
    """tag() 词性粗标的输入（token 流）不再漏全角：全角数字转出后判 m。"""
    tokens = rag_tokenizer.tokenize("１２３").split()
    assert tokens == ["123"]
    assert rag_tokenizer.tag(tokens[0]) == "m"
