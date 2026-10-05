"""句子窗口切分器回归测试：每句一单元 + 窗口元数据 + doc_id 契约。

验证核心不变量：
1. 句粒度：每条 chunk 是单句（不聚拢、不合并短句）；
2. 窗口元数据：每条 chunk 携带 expansion_type/expansion_window_size；
3. 字符不丢：strip 后拼接还原原文（句读保留）；
4. doc_id 契约：``_sw_chunk_{i}`` 连续编号；
5. 注册：DocumentRegistry 可按 'sentence_window' 取到本切分器。
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
from novamind.engines.document.splitters import SentenceWindowSplitter

pytestmark = pytest.mark.unit


def _split_docs(text: str, **kw) -> list[dict]:
    """完整 split 入口。"""
    splitter = SentenceWindowSplitter(**kw)
    return asyncio.run(
        splitter.split([{"text": text, "source": "t", "page": 1, "doc_id": "0", "type": "markdown"}])
    )


class TestSentenceGranularity:
    def test_one_chunk_per_sentence(self):
        """正例：每句一个 chunk，短句不合并（纯窗口语义）。"""
        chunks = _split_docs("甲句。乙句。丙句。")
        assert [c["text"] for c in chunks] == ["甲句。", "乙句。", "丙句。"]

    def test_no_content_loss(self):
        """字符不丢：strip 后拼接还原原文（相邻正常场景：含小数点数字不误切）。"""
        text = "版本3.14发布。第二句。"
        chunks = _split_docs(text)
        assert "".join(c["text"] for c in chunks) == text


class TestWindowMetadata:
    def test_window_metadata_on_every_chunk(self):
        """每条 chunk 携带窗口参数（chunk 自描述——检索期不回查 KB 配置）。"""
        chunks = _split_docs("甲句。乙句。", window_size=3)
        assert all(
            c["meta"] == {"expansion_type": "sentence_window", "expansion_window_size": 3}
            for c in chunks
        )

    def test_zero_window_size_is_valid_metadata(self):
        """window_size=0 是合法配置（不扩窗），元数据照常落库。"""
        chunks = _split_docs("甲句。乙句。", window_size=0)
        assert chunks[0]["meta"]["expansion_window_size"] == 0


class TestOutputContract:
    def test_doc_id_sw_chunk_numbering(self):
        """doc_id 按 ``{原doc_id}_sw_chunk_{序号}`` 连续编号。"""
        chunks = _split_docs("甲句。乙句。丙句。")
        assert [c["doc_id"] for c in chunks] == [
            "0_sw_chunk_0", "0_sw_chunk_1", "0_sw_chunk_2",
        ]
        assert all(c["type"] == "markdown" for c in chunks)
        assert all(c["source"] == "t" for c in chunks)

    def test_empty_input_returns_empty(self):
        """反例：纯空白输入产出零 chunk。"""
        assert _split_docs("   ") == []


class TestRegistry:
    def test_sentence_window_registered(self):
        """DocumentRegistry 能按 'sentence_window' 取到 SentenceWindowSplitter。"""
        assert DocumentRegistry.get_splitter_class("sentence_window") is SentenceWindowSplitter
