"""
Ollama 原生 Embedding 客户端

使用 Ollama 原生 /api/embed 端点，支持单条和批量文本向量化。
"""

from typing import List, Optional

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from novamind.shared.ai_models.base_model import BaseEmbedding
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class OllamaEmbedding(BaseEmbedding):
    """
    Ollama 原生 Embedding 客户端

    通过 Ollama 原生 API (/api/embed) 进行文本向量化。
    默认 base_url: http://localhost:11434
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "http://localhost:11434",
        model_name: str = "nomic-embed-text",
        expected_dimension: int | None = None,
        timeout: int = 60,
        max_retries: int = 3,
        max_concurrent: int = 5,
        **kwargs,
    ):
        """
        初始化 Ollama Embedding 客户端

        Args:
            api_key: API 密钥（Ollama 本地部署通常为空）
            base_url: Ollama 服务地址
            model_name: 模型名称
            expected_dimension: 期望的向量维度
            timeout: API 调用超时（秒）
            max_retries: 最大重试次数
            max_concurrent: 最大并发数
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model_name=model_name,
            expected_dimension=expected_dimension,
            timeout=timeout,
            max_retries=max_retries,
            max_concurrent=max_concurrent,
        )
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端（延迟初始化，带锁保护）"""
        async with self._get_lock():
            if self._http_client is None:
                self._http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout, connect=10.0),
                    limits=httpx.Limits(max_connections=10),
                )
        return self._http_client

    def _validate_dimension(self, embedding: list[float]) -> None:
        """验证向量维度"""
        if self.expected_dimension is not None:
            actual_dim = len(embedding)
            if actual_dim != self.expected_dimension:
                logger.error(
                    "向量维度验证失败",
                    expected=self.expected_dimension,
                    actual=actual_dim,
                    model=self.model,
                )
                raise ValueError(
                    f"向量维度不匹配: 期望 {self.expected_dimension} 维, 实际 {actual_dim} 维"
                )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError, OSError)),
        reraise=True,
    )
    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """
        调用 Ollama /api/embed 端点

        Args:
            texts: 输入文本列表

        Returns:
            嵌入向量列表
        """
        async with self._get_semaphore():
            client = await self._get_http_client()

            response = await client.post(
                f"{self.base_url}/api/embed",
                json={
                    "model": self.model,
                    "input": texts,
                },
            )
            response.raise_for_status()
            result = response.json()

            # Ollama 响应格式: {"embeddings": [[...], [...], ...]}
            embeddings = result.get("embeddings", [])

            for emb in embeddings:
                self._validate_dimension(emb)

            logger.debug(
                "Ollama Embedding 完成",
                model=self.model,
                input_count=len(texts),
                output_count=len(embeddings),
            )

            return embeddings

    async def generate_embedding(self, text: str) -> list[float]:
        """
        生成单个文本的嵌入向量

        Args:
            text: 输入文本

        Returns:
            嵌入向量
        """
        embeddings = await self._embed([text])
        return embeddings[0]

    async def generate_embeddings_batch(
        self, texts: list[str], batch_size: int = 20
    ) -> list[list[float]]:
        """
        批量生成文本的嵌入向量

        Ollama 原生支持列表输入，按 batch_size 分批调用。

        Args:
            texts: 输入文本列表
            batch_size: 批次大小

        Returns:
            嵌入向量列表
        """
        if not texts:
            return []

        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = await self._embed(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
