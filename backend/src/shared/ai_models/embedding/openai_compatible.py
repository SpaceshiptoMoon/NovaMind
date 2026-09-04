"""
OpenAI 兼容 Embedding 客户端

基于 OpenAI SDK，覆盖所有兼容 OpenAI API 的服务商：
OpenAI、智谱 AI、阿里云 DashScope、硅基流动等
"""

import traceback

import httpx
import openai
from openai import AsyncOpenAI

# openai SDK 会把底层 httpx 异常包装为自有类型（如超时 → APITimeoutError），
# tenacity 重试名单必须包含这些包装类型，否则超时/连接错误会直接穿透重试。
try:
    from openai import APIConnectionError, APITimeoutError, RateLimitError

    OPENAI_RETRY_EXCEPTIONS: tuple[type[Exception], ...] = (
        APIConnectionError,
        APITimeoutError,
        RateLimitError,
    )
except ImportError:  # pragma: no cover - openai 未安装时降级
    OPENAI_RETRY_EXCEPTIONS = ()
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import re

from novamind.shared.ai_models.base_model import BaseEmbedding, PROXY_INHERIT, build_openai_http_client
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 服务商对单批条数的硬限制报错（如 DashScope: "batch size is invalid, it should
# not be larger than 20"）。对这类确定性 400 重试无意义，必须自适应缩小批次重发。
_BATCH_LIMIT_PATTERNS = (
    re.compile(r"batch size is invalid", re.IGNORECASE),
    re.compile(r"batch.{0,20}(too|exceed|larger than)", re.IGNORECASE),
    re.compile(r"(too many|maximum).{0,20}input", re.IGNORECASE),
)


def _parse_batch_limit_error(error_text: str) -> int | None:
    """从批量超限报错文本中解析服务商允许的最大批条数；解析不出返回 None。

    示例：DashScope 报 "it should not be larger than 20" → 返回 20。
    """
    m = re.search(r"larger than\s+(\d+)", error_text, re.IGNORECASE) or re.search(
        r"maximum[^0-9]{0,20}(\d+)", error_text, re.IGNORECASE
    )
    return int(m.group(1)) if m else None


class EmbeddingDimensionError(Exception):
    """向量维度不匹配错误"""

    def __init__(self, expected: int, actual: int, model: str):
        self.expected = expected
        self.actual = actual
        self.model = model
        super().__init__(
            f"向量维度不匹配: 模型 {model} 期望 {expected} 维, 实际 {actual} 维"
        )


class OpenAICompatibleEmbedding(BaseEmbedding):
    """
    OpenAI 兼容 Embedding 客户端

    通过配置不同的 api_key / base_url / model_name 适配各种 OpenAI 兼容服务商。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        expected_dimension: int | None = None,
        timeout: int = 60,
        max_retries: int = 3,
        max_concurrent: int = 5,
        batch_size: int = 32,
        normalize: bool = True,
        proxy: object = PROXY_INHERIT,
        **kwargs,
    ):
        """
        初始化 OpenAI 兼容 Embedding 客户端

        Args:
            api_key: API 密钥
            base_url: API 基础 URL
            model_name: 嵌入模型名称
            expected_dimension: 期望的向量维度（用于验证，可选）
            timeout: API 调用超时（秒）
            max_retries: 最大重试次数
            max_concurrent: 最大并发调用数
            batch_size: 批处理大小
            normalize: 是否归一化向量
            proxy: 代理配置。PROXY_INHERIT（默认）继承环境变量代理；
                None / "" 显式禁用代理（用于直连国内服务商绕开本地代理）；
                str 代理 URL 则使用该代理。
        """
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
        self.normalize = normalize
        self.proxy = proxy
        # 服务商批量上限的学习值（取历史最小，保守安全——部分服务商上限随请求
        # token 数浮动，如 DashScope 同一模型观测到 20 与 25 两个值）。
        self._learned_batch_limit: int | None = None

        # 通过自定义 httpx.AsyncClient 控制代理语义，避免 httpx 默认从环境变量
        # 继承代理导致直连国内服务商（如 DashScope）时 TLS 握手失败。
        http_client = build_openai_http_client(
            timeout=timeout,
            max_connections=max_concurrent * 2,
            proxy=proxy,
        )
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            http_client=http_client,
            timeout=httpx.Timeout(timeout, connect=10.0),
            max_retries=max_retries,
        )

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
                raise EmbeddingDimensionError(
                    expected=self.expected_dimension,
                    actual=actual_dim,
                    model=self.model,
                )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError, OSError)
            + OPENAI_RETRY_EXCEPTIONS
        ),
        reraise=True,
    )
    async def generate_embedding(self, text: str) -> list[float]:
        """生成单个文本的嵌入向量（带重试和并发控制）"""
        async with self._get_semaphore():
            try:
                response = await self.client.embeddings.create(
                    model=self.model,
                    input=text,
                )
                embedding = response.data[0].embedding
                self._validate_dimension(embedding)
                return embedding
            except Exception as e:
                logger.error(
                    "Embedding 请求失败",
                    model=self.model,
                    base_url=self.base_url,
                    error=str(e),
                    traceback=traceback.format_exc(),
                )
                raise

    async def generate_embeddings_batch(
        self, texts: list[str], batch_size: int | None = None
    ) -> list[list[float]]:
        """批次生成文本嵌入向量

        batch_size 为 None 时使用构造器配置的 self.batch_size，
        避免方法默认值（10）与构造器默认值（32）语义脱节。

        服务商返回批量条数超限类 400 时，自适应缩小批次重发
        （不重试原批次——确定性参数错误重试同样失败），
        并记住可用批大小供后续批次直接使用。
        """
        if not texts:
            return []

        effective_batch_size = batch_size or self.batch_size
        # 历史学到的上限优先（跨调用/跨文档复用，避免每文档重复付一次 400）
        if self._learned_batch_limit is not None:
            effective_batch_size = min(effective_batch_size, self._learned_batch_limit)
        embeddings = []
        i = 0
        while i < len(texts):
            batch_texts = texts[i : i + effective_batch_size]
            try:
                batch_embeddings = await self._generate_batch(batch_texts)
            except openai.BadRequestError as e:
                limit = self._batch_limit_from_error(e)
                if limit is None or limit >= effective_batch_size or limit < 1:
                    raise
                logger.warning(
                    "批量条数超过服务商上限，自适应缩小批次",
                    model=self.model,
                    old_batch_size=effective_batch_size,
                    new_batch_size=limit,
                    error=str(e),
                )
                effective_batch_size = limit
                self._learned_batch_limit = (
                    limit
                    if self._learned_batch_limit is None
                    else min(self._learned_batch_limit, limit)
                )
                continue
            embeddings.extend(batch_embeddings)
            i += len(batch_texts)

        return embeddings

    @staticmethod
    def _batch_limit_from_error(e: Exception) -> int | None:
        """识别批量条数超限类 400，并解析服务商允许的最大条数；非此类错误返回 None。"""
        text = str(e)
        if not any(p.search(text) for p in _BATCH_LIMIT_PATTERNS):
            return None
        return _parse_batch_limit_error(text)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError, OSError)
            + OPENAI_RETRY_EXCEPTIONS
        ),
        reraise=True,
    )
    async def _generate_batch(self, batch_texts: list[str]) -> list[list[float]]:
        """单批次生成嵌入向量（带重试和并发控制）"""
        async with self._get_semaphore():
            try:
                response = await self.client.embeddings.create(
                    model=self.model,
                    input=batch_texts,
                )
                batch_embeddings = [data.embedding for data in response.data]
                for embedding in batch_embeddings:
                    self._validate_dimension(embedding)
                return batch_embeddings
            except Exception as e:
                logger.error(
                    "批量 Embedding 请求失败",
                    model=self.model,
                    base_url=self.base_url,
                    batch_size=len(batch_texts),
                    error=str(e),
                    traceback=traceback.format_exc(),
                )
                raise

    async def embed_batch(self, texts: list[str], batch_size: int | None = None) -> list[list[float]]:
        """批量生成嵌入向量（别名方法）"""
        return await self.generate_embeddings_batch(texts, batch_size)

    async def generate_embeddings_from_dict_list(
        self, text_dicts: list[dict], text_key: str = "text", batch_size: int | None = None
    ) -> list[dict]:
        """从字典列表生成嵌入向量，保留原始字典结构"""
        if not text_dicts:
            return []

        texts = [item[text_key] for item in text_dicts if text_key in item]
        embeddings = await self.generate_embeddings_batch(texts, batch_size)

        result = []
        emb_idx = 0
        for item in text_dicts:
            item_copy = item.copy()
            if text_key in item:
                item_copy["embedding"] = embeddings[emb_idx]
                emb_idx += 1
            result.append(item_copy)

        return result

    async def close(self) -> None:
        """关闭 OpenAI 客户端连接"""
        await self.client.close()
