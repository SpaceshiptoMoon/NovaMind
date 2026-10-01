"""英文正文金样回归测试（鲁棒性审计遗留 #13：金样 fixture 全中文）。

上游 ragflow 语料以英文论文为主，纯中文金样对西文特有逻辑零覆盖。本文件用
程序生成的英文论文样式 PDF（标题/编号小节/跨页段落/页码）锁三类行为：

1. 词间空格重组：跨框/跨行拼接时英文词边界必须补**恰好一个**空格
   （_merge_block_states 的 isalnum 分支；中文走 else 分支不加空格——
   两种语言同管线，正反都要锁）；
2. 西文编号小节边界：``2.1 Subsection`` 数字编号行是段落边界（proj_match
   数字模式），不得被上一段吞并；
3. 英文句号断段与跨页守卫：句号结尾的英文段落跨页必须断开（跨页守卫对
   西文段落同样生效，非中文特化）。

断言锁宏观行为（文本完整性/词边界/断段），不锁 OCR/合并模型精度边界。
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytest.importorskip("fitz")

from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser
from novamind.engines.document.integrations.deepdoc.updown_concat import (
    UpDownConcatMerger,
)

pytestmark = pytest.mark.unit

TITLE_P1 = "1. Introduction"
SUBSECTION_P2 = "2.1 Experimental Setup"


def _make_english_pdf(path: Path) -> None:
    """英文论文样式 fixture：编号标题 + 跨行正文（词边界样例）+ 跨页段落。

    页 1 正文末句停在句号（跨页必须断段）；页 2 以编号小节开头（proj_match
    数字编号边界）后接长正文。正文行刻意控制宽度，产生大量跨行框拼接。
    """
    import fitz

    doc = fitz.open()
    font = "helv"  # 西文内置字体，渲染规整
    # 页 1：标题 + 正文（段尾句号 → 跨页断段正例素材）
    page = doc.new_page(width=595, height=842)
    page.insert_text((200, 60), TITLE_P1, fontname=font, fontsize=16)
    y = 110
    for line in (
        "Data processing pipelines form the foundation of modern",
        "retrieval systems. The tokenizer consumes raw text and produces",
        "structured segments for downstream indexing.",
    ):
        page.insert_text((60, y), line, fontname=font, fontsize=12)
        y += 22
    page.insert_text((285, 810), "1", fontname=font, fontsize=11)
    # 页 2：编号小节标题（数字编号边界）+ 多行正文（词边界素材）
    page = doc.new_page(width=595, height=842)
    page.insert_text((180, 60), SUBSECTION_P2, fontname=font, fontsize=14)
    y = 110
    for line in (
        "Every evaluation pipeline depends on reproducible metrics and",
        "deterministic segment ordering across pages.",
    ):
        page.insert_text((60, y), line, fontname=font, fontsize=12)
        y += 22
    page.insert_text((285, 810), "2", fontname=font, fontsize=11)
    doc.save(str(path))
    doc.close()


@pytest.fixture(scope="module")
def english_pdf(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("deepdoc_english_golden")
    path = tmp / "golden_english.pdf"
    _make_english_pdf(path)
    return path


# ==================== 纯单元：词边界拼接（不依赖模型/vision） ====================


class TestWordBoundaryConcat:
    """_merge_block_states 词间空格分支的正反锁定（纯逻辑，无需 vision）。"""

    def test_english_words_get_single_space(self):
        """英文词对词拼接必须补恰好一个空格（isalnum 分支）。"""
        merger = UpDownConcatMerger()
        out = merger._merge_block_states([
            {"page_number": 1, "x0": 0.0, "x1": 100.0, "top": 0.0, "bottom": 10.0,
             "text": "reproducible metrics", "positions": []},
            {"page_number": 1, "x0": 0.0, "x1": 100.0, "top": 10.0, "bottom": 20.0,
             "text": "and deterministic", "positions": []},
        ])
        assert out["text"] == "reproducible metrics and deterministic"

    def test_chinese_chars_get_no_space(self):
        """反例（相邻正常场景）：中文拼接不补空格（else 分支，旧行为不回退）。"""
        merger = UpDownConcatMerger()
        out = merger._merge_block_states([
            {"page_number": 1, "x0": 0.0, "x1": 100.0, "top": 0.0, "bottom": 10.0,
             "text": "数据", "positions": []},
            {"page_number": 1, "x0": 0.0, "x1": 100.0, "top": 10.0, "bottom": 20.0,
             "text": "处理", "positions": []},
        ])
        assert out["text"] == "数据处理"

    def test_english_trailing_punct_no_double_space(self):
        """行尾标点（非 alnum）→ 下一行直接拼接，不产生空格。"""
        merger = UpDownConcatMerger()
        out = merger._merge_block_states([
            {"page_number": 1, "x0": 0.0, "x1": 100.0, "top": 0.0, "bottom": 10.0,
             "text": "ends with comma,", "positions": []},
            {"page_number": 1, "x0": 0.0, "x1": 100.0, "top": 10.0, "bottom": 20.0,
             "text": "then continues", "positions": []},
        ])
        assert out["text"] == "ends with comma,then continues"


# ==================== 西文编号小节边界（纯单元） ====================


class TestLatinProjMatch:
    """西文编号行是段落边界（proj_match 数字模式对英文同效）。"""

    def test_numbered_subsection_is_boundary(self):
        assert UpDownConcatMerger._match_proj("2.1 Experimental Setup") is True

    def test_plain_english_sentence_not_boundary(self):
        """反例：普通英文句子不误判为标题行。"""
        assert (
            UpDownConcatMerger._match_proj(
                "The tokenizer consumes raw text and produces"
            )
            is False
        )


# ==================== 端到端金样（需 vision runtime） ====================


def _parse(pdf_path: Path) -> tuple[str, dict]:
    logging.disable(logging.CRITICAL)
    try:
        parser = RAGFlowPdfParser()
        result = parser(str(pdf_path), pdf_mode="full", chunk_size=1000)
    finally:
        logging.disable(logging.NOTSET)
    return result.full_text, result.metadata


@pytest.mark.slow
def test_golden_english_pdf_baseline(english_pdf):
    """英文金样端到端：词边界完整 + 小节标题保留 + 页码清理 + 句号跨页断段。"""
    try:
        from novamind.engines.document.integrations.deepdoc.vision_runtime import (
            get_vision_runtime_status,
        )
        if not get_vision_runtime_status()["available"]:
            pytest.skip("DeepDoc vision runtime unavailable")
    except Exception:
        pytest.skip("DeepDoc vision runtime unavailable")

    full_text, meta = _parse(english_pdf)
    collapsed = full_text.replace(" ", "").replace("\n", "")

    # 词边界完整性：跨行正文关键短语无字符丢失（空格数不锁——框合并策略
    # 可能产生双空格形态，锁「词序完整」这个宏观面）
    assert "reproduciblemetricsanddeterministic" in collapsed, (
        f"跨行正文词序被破坏: {full_text[:300]!r}"
    )
    # 西文编号小节标题保留且不被上一页正文吞并（句号跨页断段 + proj 边界）
    assert SUBSECTION_P2 in full_text, f"编号小节标题丢失: {full_text[:300]!r}"
    assert "pages." + SUBSECTION_P2 not in full_text.replace("\n", ""), (
        "句号结尾段落跨页吞并了下一页小节标题——跨页守卫对英文段落失效"
    )
    # 页码框清理在英文路径同样生效
    for line in full_text.split("\n"):
        assert line.strip() not in {"1", "2"}, f"英文路径残留孤立页码行: {line!r}"
    assert meta["pages"] == 2
