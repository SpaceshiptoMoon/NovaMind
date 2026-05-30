"""
多模态嵌入模型基类

扩展 BaseEmbedding，增加图片嵌入能力。
支持文本和图片嵌入到同一向量空间（CLIP 类模型）。
"""

from abc import abstractmethod
from typing import List

from src.shared.ai_models.base_model import BaseEmbedding


class BaseMultimodalEmbedding(BaseEmbedding):
    """
    多模态嵌入模型基类

    继承 BaseEmbedding 的文本嵌入接口，
    新增 generate_image_embedding 和 generate_image_embeddings_batch 方法。
    """

    @abstractmethod
    async def generate_image_embedding(self, image_data: bytes) -> List[float]:
        """
        从图片二进制数据生成嵌入向量

        Args:
            image_data: 图片文件的二进制数据

        Returns:
            嵌入向量
        """
        pass

    async def generate_image_embeddings_batch(
        self, images: list[bytes], batch_size: int = 10
    ) -> list[list[float]]:
        """
        批量生成图片嵌入向量

        Args:
            images: 图片二进制数据列表
            batch_size: 批次大小

        Returns:
            嵌入向量列表
        """
        embeddings = []
        for i in range(0, len(images), batch_size):
            batch = images[i : i + batch_size]
            for img in batch:
                emb = await self.generate_image_embedding(img)
                embeddings.append(emb)
        return embeddings
