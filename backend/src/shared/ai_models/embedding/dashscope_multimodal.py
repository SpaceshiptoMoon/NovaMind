"""
DashScope 原生多模态 Embedding 客户端

调用阿里云 DashScope 多模态嵌入 API，支持文本和图片嵌入。
适用于 tongyi-embedding-vision-flash / tongyi-embedding-vision-plus 等模型。

API 文档：
  POST https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding

文本输入: {"text": "content"}
图片输入: {"image": "data:image/jpeg;base64,..."}
"""

import asyncio
import base64
from typing import Optional

import httpx
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

_DASHSCOPE_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"


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


class DashScopeMultimodalEmbedding(BaseMultimodalEmbedding):
    """DashScope 原生多模态 Embedding 客户端"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        model_name: str = "",
        expected_dimension: int | None = None,
        timeout: int = 60,
        max_retries: int = 3,
        max_concurrent: int = 5,
        **kwargs,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url or _DASHSCOPE_ENDPOINT,
            model_name=model_name,
            expected_dimension=expected_dimension,
            timeout=timeout,
            max_retries=max_retries,
            max_concurrent=max_concurrent,
        )
        self._http_client: Optional[httpx.AsyncClient] = None

    def _get_http_client(self) -> httpx.AsyncClient:
        """延迟创建 httpx 客户端"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._http_client

    def _validate_dimension(self, embedding: list[float]) -> None:
        if self.expected_dimension is not None and len(embedding) != self.expected_dimension:
            raise EmbeddingDimensionError(
                expected=self.expected_dimension,
                actual=len(embedding),
                model=self.model,
            )

    def _build_parameters(self) -> dict:
        """构建请求参数（包含 dimension）"""
        params = {}
        if self.expected_dimension is not None:
            params["dimension"] = self.expected_dimension
        return params

    def _parse_response(self, data: dict, context: str = "") -> list[float]:
        """解析 DashScope 响应，提取嵌入向量"""
        # 错误响应: {"code": "InvalidApiKey", "message": "..."}
        if "code" in data:
            raise RuntimeError(
                f"DashScope API 错误 [{data.get('code')}]: {data.get('message', '未知错误')}"
            )

        output = data.get("output", {})
        embeddings = output.get("embeddings", [])
        if not embeddings:
            raise RuntimeError(f"DashScope 返回空嵌入{context}")

        embedding = embeddings[0].get("embedding")
        if not embedding:
            raise RuntimeError(f"DashScope 返回的嵌入向量为空{context}")

        return embedding

    # ---- 文本嵌入 ----

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError, OSError)),
        reraise=True,
    )
    async def generate_embedding(self, text: str) -> list[float]:
        async with self._get_semaphore():
            client = self._get_http_client()
            payload = {
                "model": self.model,
                "input": {"contents": [{"text": text}]},
                "parameters": self._build_parameters(),
            }
            resp = await client.post(_DASHSCOPE_ENDPOINT, json=payload)
            resp.raise_for_status()
            data = resp.json()
            embedding = self._parse_response(data, "(文本)")
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
            for text in batch:
                emb = await self.generate_embedding(text)
                embeddings.append(emb)
        return embeddings

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
            client = self._get_http_client()
            payload = {
                "model": self.model,
                "input": {"contents": [{"image": data_url}]},
                "parameters": self._build_parameters(),
            }
            resp = await client.post(_DASHSCOPE_ENDPOINT, json=payload)
            resp.raise_for_status()
            data = resp.json()
            embedding = self._parse_response(data, "(图片)")
            self._validate_dimension(embedding)
            return embedding

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
