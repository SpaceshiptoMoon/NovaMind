"""层级切分器回归测试：章节边界 + 特殊对象不二次切分 + content_type 元数据契约。

验证核心不变量：
1. 章节边界：H1/H2 切章，H3+ 不切；
2. 特殊对象：fenced code / markdown 管道表 / HTML 表格独立成块不二次切分，
   content_type 分别为 code/table；
3. 章节锚点：每章节首个块是 content_type=text 锚点，带标题+首段；
4. 正文细分：正文按 chunk_size 切，meta 带所属 section_slot；
5. 退化：无标题文本单章节；纯空白输入零 chunk；纯特殊对象章节无锚点；
6. 配置矛盾：chunk_overlap >= chunk_size 构造抛 ValueError；
7. 注册：DocumentRegistry 可按 'hierarchical' 取到本切分器。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.pipeline.document_loader import DocumentRegistry
from novamind.engines.document.splitters import HierarchicalSplitter

pytestmark = pytest.mark.unit


def _split_docs(text: str, **kw) -> list[dict]:
    """完整 split 入口（测试用小 chunk_size 时默认关 overlap 防配置矛盾）。"""
    kw.setdefault("chunk_overlap", 0)
    splitter = HierarchicalSplitter(**kw)
    return asyncio.run(
        splitter.split([{"text": text, "source": "t", "page": 1, "doc_id": "0", "type": "text"}])
    )


class TestConfigValidation:
    def test_overlap_ge_chunk_size_rejected(self):
        """配置矛盾：chunk_overlap >= chunk_size 构造即抛。"""
        with pytest.raises(ValueError, match="chunk_overlap"):
            HierarchicalSplitter(chunk_size=100, chunk_overlap=100)

    def test_tiny_chunk_size_rejected(self):
        """配置矛盾：chunk_size < 50 构造即抛。"""
        with pytest.raises(ValueError, match="chunk_size"):
            HierarchicalSplitter(chunk_size=10)


class TestSectionBoundaries:
    def test_h1_h2_split_h3_not(self):
        """正例：H1/H2 是章节边界，H3 不是。"""
        text = "# A\n内容a\n## B\n内容b\n### C\n内容c\n# D\n内容d"
        chunks = _split_docs(text, chunk_size=1000)
        anchors = [
            c for c in chunks
            if c["meta"]["content_type"] == "text" and c["text"].startswith("#")
        ]
        # 3 章节（A、B、D）；C 归入 B 章正文
        anchor_texts = [c["text"] for c in anchors]
        assert any(t.startswith("# A") for t in anchor_texts)
        assert any(t.startswith("## B") for t in anchor_texts)
        assert any(t.startswith("# D") for t in anchor_texts)
        assert not any(t.startswith("### C") for t in anchor_texts)

    def test_section_slots_ordered(self):
        """section_slot 按章节序数递增，同章节块共享 slot。"""
        text = "# A\n" + "甲" * 300 + "\n# B\n" + "乙" * 300
        chunks = _split_docs(text, chunk_size=200)
        slots = {c["meta"]["section_slot"] for c in chunks}
        assert slots == {0, 1}
        a_chunks = [c for c in chunks if c["meta"]["section_slot"] == 0]
        assert all("甲" in c["text"] or c["text"].startswith("#") for c in a_chunks)


class TestSpecialObjects:
    def test_code_block_not_split(self):
        """fenced code 整块保留，content_type=code，不按 chunk_size 二次切分。"""
        code_body = "\n".join(f"line_{i} = {i}" for i in range(100))
        text = f"# A\n正文\n```python\n{code_body}\n```"
        chunks = _split_docs(text, chunk_size=100)
        code_chunks = [c for c in chunks if c["meta"]["content_type"] == "code"]
        assert len(code_chunks) == 1
        assert code_chunks[0]["text"].startswith("```python")
        assert code_chunks[0]["text"].rstrip().endswith("```")
        assert "line_99" in code_chunks[0]["text"]

    def test_unclosed_fence_eats_to_end(self):
        """未闭合围栏吃到文末不丢内容（失败方向：能力缺失优于丢内容）。"""
        text = "# A\n```python\nx = 1\ny = 2"
        chunks = _split_docs(text, chunk_size=100)
        code_chunks = [c for c in chunks if c["meta"]["content_type"] == "code"]
        assert len(code_chunks) == 1
        assert "y = 2" in code_chunks[0]["text"]

    def test_markdown_pipe_table_not_split(self):
        """markdown 管道表整块保留，content_type=table。"""
        table = "| 列1 | 列2 |\n| --- | --- |\n| a | b |\n| c | d |"
        text = f"# A\n正文\n{table}\n表后正文"
        chunks = _split_docs(text, chunk_size=100)
        table_chunks = [c for c in chunks if c["meta"]["content_type"] == "table"]
        assert len(table_chunks) == 1
        assert "| c | d |" in table_chunks[0]["text"]

    def test_html_table_not_split(self):
        """deepdoc 渲染的 HTML 表格整块保留，content_type=table。"""
        table = '<table><tr><td>单元格甲' * 50 + "</td></tr></table>"
        text = f"# A\n正文\n{table}"
        chunks = _split_docs(text, chunk_size=100)
        table_chunks = [c for c in chunks if c["meta"]["content_type"] == "table"]
        assert len(table_chunks) == 1
        assert table_chunks[0]["text"].startswith("<table")

    def test_single_pipe_line_not_table(self):
        """反例：单行含管道的普通文本不误判为表。"""
        text = "# A\na | b | c 普通说明文字"
        chunks = _split_docs(text, chunk_size=1000)
        assert not any(c["meta"]["content_type"] == "table" for c in chunks)


class TestSectionAnchor:
    def test_anchor_is_first_block_of_section(self):
        """锚点块是该章节列表位置首个块（content_type=text）。"""
        text = "# 标题甲\n首段内容。\n```python\nx=1\n```"
        chunks = _split_docs(text, chunk_size=1000)
        assert chunks[0]["meta"]["content_type"] == "text"
        assert chunks[0]["text"].startswith("# 标题甲")
        assert "首段内容" in chunks[0]["text"]

    def test_pure_special_section_has_no_anchor(self):
        """纯特殊对象章节无锚点（该章检索只走特殊对象方向）。"""
        text = "## 数据表\n| a | b |\n| --- | --- |\n| 1 | 2 |"
        chunks = _split_docs(text, chunk_size=1000)
        assert not any(
            c["meta"]["content_type"] == "text" and c["text"].startswith("##") for c in chunks
        )
        assert any(c["meta"]["content_type"] == "table" for c in chunks)

    def test_no_heading_degrades_to_single_section(self):
        """无标题文本单章节，语义不退化（全部块 section_slot=0）。"""
        text = "无标题正文。" * 50
        chunks = _split_docs(text, chunk_size=100)
        assert chunks
        assert all(c["meta"]["section_slot"] == 0 for c in chunks)


class TestMetadataContract:
    def test_all_chunks_carry_expansion_type(self):
        """所有块带 expansion_type=hierarchical（检索期扩展开关）。"""
        text = "# A\n正文\n```py\nx=1\n```\n| a |\n| --- |\n| b |"
        chunks = _split_docs(text, chunk_size=1000)
        assert chunks
        assert all(c["meta"].get("expansion_type") == "hierarchical" for c in chunks)

    def test_content_type_values_constrained(self):
        """content_type 只取 text/table/code 三值。"""
        text = "# A\n正文\n```py\nx=1\n```\n| a |\n| --- |\n| b |"
        chunks = _split_docs(text, chunk_size=1000)
        assert {c["meta"]["content_type"] for c in chunks} <= {"text", "table", "code"}
        assert {c["meta"]["content_type"] for c in chunks} == {"text", "code", "table"}


class TestDegenerateCases:
    def test_empty_input_returns_empty(self):
        """反例：纯空白输入产出零 chunk。"""
        assert _split_docs("   ") == []

    def test_plain_text_short_degenerates(self):
        """相邻正常场景：短纯文本 → 1 锚点块（等价普通切分）。"""
        chunks = _split_docs("短文档内容。", chunk_size=1000)
        assert len(chunks) == 1
        assert chunks[0]["meta"]["content_type"] == "text"


class TestRegistry:
    def test_hierarchical_registered(self):
        """DocumentRegistry 能按 'hierarchical' 取到 HierarchicalSplitter。"""
        assert DocumentRegistry.get_splitter_class("hierarchical") is HierarchicalSplitter
