"""
DashScope 原生多模态 Embedding 客户端

通过 dashscope SDK 调用阿里百炼多模态嵌入 API，支持文本和图片嵌入。
适用于 tongyi-embedding-vision-flash / tongyi-embedding-vision-plus 等模型。

SDK 使用方式：
  文本: AioMultiModalEmbedding.call(model=..., input=[{'text': '...'}], api_key=...)
  图片: AioMultiModalEmbedding.call(model=..., input=[{'image': 'url'}], api_key=...)
"""

import asyncio
import base64
import tempfile
from typing import Optional

from src.shared.ai_models.embedding.multimodal_embedding import BaseMultimodalEmbedding
from src.shared.ai_models.embedding.openai_compatible import EmbeddingDimensionError
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


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


def _get_extension(mime_type: str) -> str:
    """MIME 类型 → 扩展名"""
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}.get(
        mime_type, ".png"
    )


class DashScopeMultimodalEmbedding(BaseMultimodalEmbedding):
    """DashScope 原生多模态 Embedding 客户端（基于 dashscope SDK）"""

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
            base_url=base_url,
            model_name=model_name,
            expected_dimension=expected_dimension,
            timeout=timeout,
            max_retries=max_retries,
            max_concurrent=max_concurrent,
        )

    def _validate_dimension(self, embedding: list[float]) -> None:
        if self.expected_dimension is not None and len(embedding) != self.expected_dimension:
            raise EmbeddingDimensionError(
                expected=self.expected_dimension,
                actual=len(embedding),
                model=self.model,
            )

    @staticmethod
    def _parse_response(resp, context: str = "") -> list[float]:
        """解析 DashScope SDK 响应，提取嵌入向量"""
        if resp.status_code != 200:
            raise RuntimeError(
                f"DashScope API 错误 [{resp.status_code}] "
                f"{getattr(resp, 'code', '')}: {getattr(resp, 'message', '未知错误')}"
            )

        output = getattr(resp, "output", None)
        if not output:
            raise RuntimeError(f"DashScope 返回空输出{context}")

        embeddings = output.get("embeddings", [])
        if not embeddings:
            raise RuntimeError(f"DashScope 返回空嵌入{context}")

        embedding = embeddings[0].get("embedding")
        if not embedding:
            raise RuntimeError(f"DashScope 返回的嵌入向量为空{context}")

        return embedding

    # ---- 文本嵌入 ----

    async def generate_embedding(self, text: str) -> list[float]:
        async with self._get_semaphore():
            for attempt in range(self.max_retries):
                try:
                    import dashscope

                    loop = asyncio.get_running_loop()
                    resp = await loop.run_in_executor(
                        None,
                        lambda: dashscope.MultiModalEmbedding.call(
                            model=self.model,
                            input=[{"text": text}],
                            api_key=self.api_key,
                        ),
                    )
                    embedding = self._parse_response(resp, "(文本)")
                    self._validate_dimension(embedding)
                    return embedding
                except EmbeddingDimensionError:
                    raise
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        raise RuntimeError(
                            f"DashScope 文本嵌入失败（重试 {self.max_retries} 次后）: {e}"
                        ) from e
                    logger.debug(
                        "DashScope 文本嵌入重试",
                        attempt=attempt + 1,
                        error=str(e),
                    )
                    await asyncio.sleep(min(2 ** attempt, 10))

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

    async def generate_image_embedding(self, image_data: bytes) -> list[float]:
        """从图片二进制数据生成嵌入向量（通过 SDK 上传文件）"""
        async with self._get_semaphore():
            for attempt in range(self.max_retries):
                try:
                    import dashscope

                    # SDK 支持 data URI 格式的 base64 图片
                    mime_type = _detect_image_mime(image_data)
                    b64 = base64.b64encode(image_data).decode("utf-8")
                    data_url = f"data:{mime_type};base64,{b64}"

                    loop = asyncio.get_running_loop()
                    resp = await loop.run_in_executor(
                        None,
                        lambda: dashscope.MultiModalEmbedding.call(
                            model=self.model,
                            input=[{"image": data_url}],
                            api_key=self.api_key,
                        ),
                    )
                    embedding = self._parse_response(resp, "(图片)")
                    self._validate_dimension(embedding)
                    return embedding
                except EmbeddingDimensionError:
                    raise
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        raise RuntimeError(
                            f"DashScope 图片嵌入失败（重试 {self.max_retries} 次后）: {e}"
                        ) from e
                    logger.debug(
                        "DashScope 图片嵌入重试",
                        attempt=attempt + 1,
                        error=str(e),
                    )
                    await asyncio.sleep(min(2 ** attempt, 10))

    async def close(self) -> None:
        """SDK 无需手动关闭资源"""
        pass
