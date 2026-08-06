"""
知识空间信息端口 KnowledgeSpaceInfoPort，供 user 服务查询空间绑定模型。

端口中立不依赖任何 feature，宿主适配器在 adapters/ 实现。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol, runtime_checkable


@dataclass
class SpaceEmbeddingUsage:
    """使用某 Embedding 模型的空间信息（删除影响检查用）。"""

    space_id: int
    space_name: str


@runtime_checkable
class KnowledgeSpaceInfoPort(Protocol):
    """知识空间信息端口：供 user feature 查询空间级 embedding 模型绑定。"""

    async def find_spaces_using_embedding_model(
        self, model_name: str
    ) -> List[SpaceEmbeddingUsage]:
        """返回所有未删除、且空间配置 ``embedding.model == model_name`` 的空间。

        Args:
            model_name: 待删除的 embedding 模型名

        Returns:
            命中空间列表（空列表表示无空间使用，可安全删除）
        """
        ...


__all__ = ["KnowledgeSpaceInfoPort", "SpaceEmbeddingUsage"]