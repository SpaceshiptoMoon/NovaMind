"""统一文档块模型回归：HTML 表格转 Markdown / 块序列化 / runtime 出口。"""
import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit

from novamind.engines.document.integrations.deepdoc.core.document_model import (
    KIND_HEADING,
    KIND_TABLE,
    KIND_TEXT,
    UnifiedBlock,
    blocks_to_markdown,
    chunks_to_markdown,
    html_table_to_markdown,
)
from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
    DeepDocParser,
)


def test_html_table_to_markdown_basic():
    """caption + th/td 结构转 Markdown 表格。"""
    html = (
        "<table><caption>Sheet!A1:B2</caption>"
        "<tr><th>名称</th><th>数量</th></tr>"
        "<tr><td>扳手</td><td>12</td></tr></table>"
    )
    md = html_table_to_markdown(html)
    assert md.startswith("*Sheet!A1:B2*")
    assert "| 名称 | 数量 |" in md
    assert "| --- | --- |" in md
    assert "| 扳手 | 12 |" in md


def test_html_table_to_markdown_escapes_and_entities():
    """单元格内竖线转义、HTML 实体解码、br 处理。"""
    html = "<table><tr><th>a|b</th></tr><tr><td>&lt;x&gt;</td></tr></table>"
    md = html_table_to_markdown(html)
    assert "a\\|b" in md
    assert "<x>" in md


def test_html_table_to_markdown_invalid_returns_original():
    """非法 HTML 片段解析失败时原样返回（产物可读性降级优于内容丢失）。"""
    broken = "<table><tr><td>unclosed"
    assert html_table_to_markdown(broken) == broken


def test_blocks_to_markdown_heading_and_table():
    """标题层级映射 # 前缀；HTML 表格块自动转换。"""
    blocks = [
        UnifiedBlock(kind=KIND_HEADING, text="季度报告 > 财务", level=2),
        UnifiedBlock(kind=KIND_TEXT, text="正文段落。"),
        UnifiedBlock(
            kind=KIND_TABLE,
            text="<table><tr><th>A</th></tr><tr><td>1</td></tr></table>",
            is_html=True,
        ),
    ]
    md = blocks_to_markdown(blocks)
    assert "## 季度报告 > 财务" in md
    assert "正文段落。" in md
    assert "| A |" in md


def test_chunks_to_markdown_mixed():
    """含 HTML 表格的 chunk 转换、纯文本 chunk 原样。"""
    chunks = [
        "纯文本段落。",
        "<table><tr><th>H</th></tr><tr><td>v</td></tr></table>",
    ]
    md = chunks_to_markdown(chunks)
    assert "纯文本段落。" in md
    assert "| H |" in md


def test_parse_result_markdown_exit_docx(tmp_path):
    """runtime 层 docx 产物带 markdown 与 document_blocks（防字段丢失回归）。"""
    from docx import Document as DocxDocument

    doc = DocxDocument()
    doc.add_heading("季度报告", level=1)
    doc.add_paragraph("正文段落。")
    table = doc.add_table(rows=2, cols=2)
    for idx, value in enumerate(["科目", "预算"]):
        table.rows[0].cells[idx].text = value
    for idx, value in enumerate(["人力", "100"]):
        table.rows[1].cells[idx].text = value
    path = tmp_path / "md.docx"
    doc.save(path)

    result = asyncio.run(
        DeepDocParser().parse(path, parsing_config={}, splitting_config={"chunk_size": 500})
    )
    assert "# 季度报告" in result.markdown
    assert "| --- |" in result.markdown, "表格应转 Markdown 表格"
    kinds = {b["kind"] for b in result.metadata["document_blocks"]}
    assert {KIND_HEADING, KIND_TABLE, KIND_TEXT} <= kinds
