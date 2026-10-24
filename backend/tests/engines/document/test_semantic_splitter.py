"""SemanticSplitter 专项单测（此前全库零覆盖）。

覆盖三块：
1. 基础切分行为：空文本 / 单块直通 / 语义断点切分 / 尺寸上限强制切分；
2. 零向量防护：embedding 客户端退化返回全零向量时不得产生 NaN
   （NaN < threshold 恒 False 会把全部块静默合并成一块），应按
   「完全不相似 → 切分」的安全方向退化；
3. CJK 拼接：中文块合并零空格（英文空格是检索分词噪声），
   英文/数字边界保留空格。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.splitters.semantic_splitter import (
    SemanticSplitter,
    _is_cjk,
    _join_chunks,
)

pytestmark = pytest.mark.unit


class ScriptedEmbedding:
    """按预置向量表返回 embedding 的桩客户端（下标循环取用）。"""

    def __init__(self, vectors: list[list[float]]):
        self._vectors = vectors

    async def generate_embeddings_batch(self, texts, batch_size=None):  # noqa: ARG002
        return [list(self._vectors[i % len(self._vectors)]) for i in range(len(texts))]


class ZeroEmbedding:
    """全部返回零向量的退化客户端（NaN 复现路径）。"""

    async def generate_embeddings_batch(self, texts, batch_size=None):  # noqa: ARG002
        return [[0.0] * 8 for _ in texts]


class HashEmbedding:
    """确定性 bigram 计数向量：相同文本相似、不同文本大概率远离。"""

    async def generate_embeddings_batch(self, texts, batch_size=None):  # noqa: ARG002
        return [self._embed(t) for t in texts]

    @staticmethod
    def _embed(text: str, dim: int = 64) -> list[float]:
        import hashlib

        vec = [0.0] * dim
        for i in range(len(text) - 1):
            digest = hashlib.md5(text[i : i + 2].encode("utf-8")).hexdigest()
            vec[int(digest, 16) % dim] += 1.0
        return vec


def _split(text: str, client, **kwargs) -> list[str]:
    splitter = SemanticSplitter(embedding_client=client, **kwargs)
    docs = [{"text": text, "source": "t", "doc_id": "0", "type": "text"}]
    return [d["text"] for d in asyncio.run(splitter.split(docs))]


class TestBasicSplitting:
    def test_empty_text_returns_no_chunks(self):
        assert _split("", HashEmbedding()) == []

    def test_whitespace_only_returns_no_chunks(self):
        assert _split("   \n\t  ", HashEmbedding()) == []

    def test_single_small_chunk_passthrough(self):
        """短文本初步切分仅 1 块 → 不触发 embedding，原样返回。"""
        text = "只有一个短句。"
        assert _split(text, ZeroEmbedding(), max_chunk_size=500) == [text]

    def test_dissimilar_chunks_split(self):
        """相邻块互异（正交向量，相似度 0 < 0.5）→ 全部切开。"""
        text = "。".join(f"主题甲的第{i}段内容" * 8 for i in range(6)) + "。"
        chunks = _split(text, ScriptedEmbedding([[1.0, 0.0], [0.0, 1.0]]),
                        max_chunk_size=120, similarity_threshold=0.5)
        assert len(chunks) >= 2

    def test_similar_chunks_merge(self):
        """相邻块同向量（相似度 1.0 ≥ 0.5）且不超限 → 合并。"""
        text = "。".join(f"同一主题的第{i}段" for i in range(4)) + "。"
        chunks = _split(text, ScriptedEmbedding([[1.0, 0.0]]),
                        max_chunk_size=10_000, similarity_threshold=0.5)
        assert len(chunks) == 1

    def test_max_chunk_size_forces_split(self):
        """相似但合并超限 → 强制切开（尺寸硬上限优先）。"""
        unit = "同主题内容块" * 8
        text = "。".join([unit] * 6) + "。"
        chunks = _split(text, ScriptedEmbedding([[1.0, 0.0]]),
                        max_chunk_size=len(unit) + 10, similarity_threshold=0.9)
        assert len(chunks) >= 2
        assert all(len(c) <= len(unit) * 2 + 10 for c in chunks)


class TestZeroVectorGuard:
    def test_zero_vectors_do_not_merge_all(self):
        """全零向量 → NaN 防护生效：按不相似处理，块不被静默合并。"""
        text = "。".join(f"主题第{i}段内容" * 8 for i in range(6)) + "。"
        chunks = _split(text, ZeroEmbedding(), max_chunk_size=120,
                        similarity_threshold=0.5)
        assert len(chunks) >= 2, "零向量被当成高相似合并——NaN 防护失效"

    def test_zero_vectors_produce_no_nan_artifacts(self):
        text = "。".join(f"主题第{i}段内容" * 8 for i in range(4)) + "。"
        chunks = _split(text, ZeroEmbedding(), max_chunk_size=120)
        assert all("nan" not in c.lower() for c in chunks)


class TestCjkJoin:
    def test_cjk_boundary_no_space(self):
        assert _join_chunks("第一段中文", "第二段中文") == "第一段中文第二段中文"

    def test_latin_boundary_keeps_space(self):
        assert _join_chunks("english part", "another part") == "english part another part"

    def test_cjk_to_latin_keeps_space(self):
        assert _join_chunks("中文块", "english") == "中文块 english"

    def test_cjk_punctuation_counts_as_cjk(self):
        assert _is_cjk("。") and _is_cjk("，") and _is_cjk("ｗ")
        assert not _is_cjk("a") and not _is_cjk("1") and not _is_cjk(" ")

    def test_merged_chinese_chunk_has_no_internal_spaces(self):
        """端到端：中文块合并后不引入拼接空格。"""
        unit = "同主题中文内容描述"
        text = "。".join([unit] * 5) + "。"
        chunks = _split(text, ScriptedEmbedding([[1.0, 0.0]]),
                        max_chunk_size=10_000, similarity_threshold=0.5)
        assert len(chunks) == 1
        assert " " not in chunks[0], f"中文合并引入空格：{chunks[0]!r}"
