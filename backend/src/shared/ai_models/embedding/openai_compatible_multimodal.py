"""
OpenAI 兼容多模态 Embedding 客户端

支持通过 OpenAI 兼容 API 进行文本和图片嵌入。
覆盖 SiliconFlow、Jina AI 等提供多模态嵌入 API 的服务商。

图片嵌入格式：
  embeddings.create(input=[{"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}])
文本嵌入格式：
  embeddings.create(input=[text]) — 标准 OpenAI 格式
"""

import asyncio
import base64
from typing import Optional

import httpx
from openai import AsyncOpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.shared.ai_models.embedding.multimodal_embedding import BaseMultimodalEmbedding
from src.shared.ai_models.embedding.openai_compatible import EmbeddingDimensionError
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 图片扩展名到 MIME 类型的映射
_IMAGE_MIME_MAP = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}


def _detect_image_mime(data: bytes) -> str:
    """通过魔数检测图片 MIME 类型"""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if data[:3] == b'\xff\xd8\xff':
        return "image/jpeg"
    if data[:4] == b'GIF8':
        return "image/gif"
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "image/webp"
    return "image/jpeg"


class OpenAICompatibleMultimodalEmbedding(BaseMultimodalEmbedding):
    """OpenAI 兼容多模态 Embedding 客户端"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        expected_dimension: int | None = None,
        timeout: int = 60,
        max_retries: int = 3,
        max_concurrent: int = 5,
        batch_size: int = 10,
        **kwargs,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            expected_dimension=expected_dimension,
            timeout=timeout,
            max_retries=max_retries,
            max_concurrent=max_concurrent,
        )
        self.batch_size = batch_size
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
            max_retries=max_retries,
        )

    def _validate_dimension(self, embedding: list[float]) -> None:
        if self.expected_dimension is not None:
            actual_dim = len(embedding)
            if actual_dim != self.expected_dimension:
                raise EmbeddingDimensionError(
                    expected=self.expected_dimension,
                    actual=actual_dim,
                    model=self.model,
                )

    # ---- 文本嵌入（复用标准 OpenAI 格式）----

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError, OSError)),
        reraise=True,
    )
    async def generate_embedding(self, text: str) -> list[float]:
        async with self._get_semaphore():
            response = await self.client.embeddings.create(
                model=self.model,
                input=text,
            )
            embedding = response.data[0].embedding
            self._validate_dimension(embedding)
            return embedding

    async def generate_embeddings_batch(
        self, texts: list[str], batch_size: int = 10
    ) -> list[list[float]]:
        if not texts:
            return []
        embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_embs = await self._generate_text_batch(batch)
            embeddings.extend(batch_embs)
        return embeddings

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError, OSError)),
        reraise=True,
    )
    async def _generate_text_batch(self, texts: list[str]) -> list[list[float]]:
        async with self._get_semaphore():
            response = await self.client.embeddings.create(
                model=self.model,
                input=texts,
            )
            batch_embs = [d.embedding for d in response.data]
            for emb in batch_embs:
                self._validate_dimension(emb)
            return batch_embs

    # ---- 图片嵌入 ----

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError, OSError)),
        reraise=True,
    )
    async def generate_image_embedding(self, image_data: bytes) -> list[float]:
        """从图片二进制数据生成嵌入向量"""
        mime_type = _detect_image_mime(image_data)
        b64 = base64.b64encode(image_data).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64}"

        async with self._get_semaphore():
            response = await self.client.embeddings.create(
                model=self.model,
                input=[{
                    "type": "image_url",
                    "image_url": {"url": data_url},
                }],
            )
            embedding = response.data[0].embedding
            self._validate_dimension(embedding)
            return embedding

    async def close(self) -> None:
        await self.client.close()
