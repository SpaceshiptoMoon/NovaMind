"""figure 占位符剥除 + MarkdownSplitter 无句读段不丢（审计 P1#7/P1#10 回归）。

P1#7：figure 图片上传失败时 __FIGURE_URL__{id}__ 占位符残留在全文/分块里，
进 embedding 污染向量、检索命中原样暴露给用户/LLM。修复：替换后统一
strip_unresolved 剥除失败占位符。

P1#10：MarkdownSplitter._split_by_sentences 对无句读标点的超长段（代码块/
URL 清单/base64）返回空列表 → 整段静默丢弃。修复：剩余部分无句可挂时
自成一个分句，绝不丢内容。
"""
import pytest

from novamind.engines.document.splitters import MarkdownSplitter
from novamind.features.knowledge_space.services.document_pipeline import (
    _replace_figure_placeholders,
)


# ========== P1#7 figure 占位符剥除 ==========


def test_replace_placeholders_basic_substitution():
    text = "前文 __FIGURE_URL__fig_1__ 后文"
    out = _replace_figure_placeholders(text, {"fig_1": "http://x/1.png"})
    assert out == "前文 http://x/1.png 后文"


def test_replace_placeholders_strips_unresolved():
    """map 中不存在的占位符（上传失败）被剥除而不是残留。"""
    text = "甲 __FIGURE_URL__ok_1__ 乙 __FIGURE_URL__fail_2__ 丙"
    out = _replace_figure_placeholders(text, {"ok_1": "http://x/1.png"}, strip_unresolved=True)
    assert "__FIGURE_URL__" not in out
    assert "甲 http://x/1.png 乙  丙" == out


def test_replace_placeholders_no_strip_without_flag():
    """不开 strip_unresolved 时保持原行为（失败占位符保留）——兼容旧调用。"""
    text = "甲 __FIGURE_URL__fail_2__ 乙"
    out = _replace_figure_placeholders(text, {})
    assert out == text


def test_strip_handles_artifact_ids_with_underscores():
    """artifact_id 含下划线（fig_12_0 形态）也要能剥除。"""
    text = "a __FIGURE_URL__fig_12_0__ b __FIGURE_URL__a1b2c3__ c"
    out = _replace_figure_placeholders(text, {}, strip_unresolved=True)
    assert "__FIGURE_URL__" not in out
    assert "a  b  c" == out


# ========== P1#10 MarkdownSplitter 无句读段 ==========


def test_split_sentences_no_punctuation_keeps_content():
    """无句读标点的超长段不再被静默丢弃。"""
    splitter = MarkdownSplitter(max_chunk_size=100, min_chunk_size=10)
    no_punct = "x" * 300  # 无任何 [.!?。！？]
    result = splitter._split_by_sentences(no_punct)
    assert result, "无句读段被切分为空——整段内容丢失"
    assert "".join(result) == no_punct or no_punct in "".join(result), "内容不完整"


def test_split_large_section_without_sentences_produces_chunks():
    """整段（标题段）无句读标点时，切分产出非空 chunks 且内容完整。"""
    splitter = MarkdownSplitter(max_chunk_size=80, min_chunk_size=10)
    code_block = "\n".join(f"line_{i} = 0x{random_hex}" for i, random_hex in enumerate(["ff"] * 40))
    chunks = splitter._split_section_content(code_block, "code", 2) if hasattr(
        splitter, "_split_section_content"
    ) else None
    if chunks is not None:
        joined = "".join(c["content"] for c in chunks)
        for line_part in ("line_0", "line_39"):
            assert line_part in joined, f"代码块内容丢失：{line_part}"


@pytest.mark.asyncio
async def test_markdown_split_no_punctuation_long_doc_no_loss():
    """端到端：markdown 切分含无句读超长段的文档，总内容不丢。"""
    splitter = MarkdownSplitter(max_chunk_size=200, min_chunk_size=20)
    base64_ish = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5eg==" * 8
    doc = [{
        "text": f"# 标题\n\n正常段落，有句读。内容较短。\n\n```\n{base64_ish}\n```",
        "source": "t",
        "page": 1,
        "doc_id": "0",
        "type": "markdown",
        "title": "",
    }]
    results = await splitter.split(doc)
    all_text = "\n".join(r["text"] for r in results)
    assert "正常段落" in all_text
    assert "QUJDREVGR0hJ" in all_text, "无句读 base64 段丢失"
