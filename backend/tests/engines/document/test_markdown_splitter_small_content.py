"""MarkdownSplitter 回归测试：覆盖短文本不应切成 0 chunk 的兜底。"""
import pytest

from novamind.engines.document.splitters.markdown_splitter import MarkdownSplitter


@pytest.mark.asyncio
async def test_small_content_returns_single_chunk():
    """非空但 < min_chunk_size 的文本应返回 1 个 chunk，而不是 0 个。

    复现 DeepDoc full_text 重切分场景：full_text 仅 163 字、min_chunk_size=500，
    原实现返回 0 chunk，导致短文档入库为空。
    """
    splitter = MarkdownSplitter(max_chunk_size=2000, min_chunk_size=500)
    documents = [{"text": "这是一段很短的内容", "source": "", "metadata": {}}]
    chunks = await splitter.split(documents)
    assert len(chunks) == 1
    assert "这是一段很短的内容" in chunks[0]["text"]


@pytest.mark.asyncio
async def test_empty_content_returns_zero_chunks():
    """空文本仍应返回 0 chunk（兜底只对非空文本生效）。"""
    splitter = MarkdownSplitter(max_chunk_size=2000, min_chunk_size=500)
    documents = [{"text": "   ", "source": "", "metadata": {}}]
    chunks = await splitter.split(documents)
    assert chunks == []