"""
基于 Embedding 的评估器

提供余弦相似度计算，用于多种评估策略
"""
import math
from typing import List

from src.shared.ai_models.base_model import BaseEmbedding
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class EmbeddingEvaluator:
    """Embedding 评估器"""

    def __init__(self, embedding_client: BaseEmbedding):
        self.embedding_client = embedding_client

    async def compute_similarity(self, text_a: str, text_b: str) -> float:
        """计算两段文本的 Embedding 余弦相似度"""
        embeddings = await self.embedding_client.generate_embeddings_batch([text_a, text_b])
        return _cosine_similarity(embeddings[0], embeddings[1])

    async def compute_similarity_batch(self, text_pairs: List[tuple[str, str]]) -> List[float]:
        """批量计算文本对的余弦相似度"""
        all_texts = []
        for a, b in text_pairs:
            all_texts.extend([a, b])

        embeddings = await self.embedding_client.generate_embeddings_batch(all_texts)

        results = []
        for i in range(len(text_pairs)):
            sim = _cosine_similarity(embeddings[i * 2], embeddings[i * 2 + 1])
            results.append(sim)
        return results

    async def similarity_to_score(self, text_a: str, text_b: str) -> int:
        """计算余弦相似度并映射到 1-10 分"""
        sim = await self.compute_similarity(text_a, text_b)
        return _similarity_to_10(sim)

    async def avg_similarity_to_score(self, reference: str, candidates: List[str]) -> tuple[float, int]:
        """计算 reference 与所有 candidates 的平均相似度，映射到 1-10 分"""
        pairs = [(reference, c) for c in candidates]
        similarities = await self.compute_similarity_batch(pairs)
        avg_sim = sum(similarities) / len(similarities) if similarities else 0.0
        return avg_sim, _similarity_to_10(avg_sim)


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _similarity_to_10(similarity: float) -> int:
    """将 0-1 的相似度映射到 1-10 分"""
    # 余弦相似度通常在 0.3-1.0 之间，线性映射可能导致分数偏低
    # 使用映射公式：score = max(1, round(similarity * 10))
    score = round(similarity * 10)
    return max(1, min(10, score))
