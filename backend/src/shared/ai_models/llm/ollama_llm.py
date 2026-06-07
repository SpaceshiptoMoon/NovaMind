"""
Ollama 原生 LLM 客户端

使用 Ollama 原生 /api/chat 端点，支持文本生成和流式生成。
"""

import asyncio
import json
from typing import Optional, AsyncGenerator

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.shared.ai_models.base_model import BaseLLM
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class OllamaLLM(BaseLLM):
    """
    Ollama 原生 LLM 客户端

    通过 Ollama 原生 API (/api/chat) 进行文本生成。
    默认 base_url: http://localhost:11434
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "http://localhost:11434",
        model_name: str = "llama3",
        timeout: int = 60,
        max_retries: int = 3,
        max_concurrent: int = 10,
        default_system_prompt: str = "You are a helpful assistant.",
        **kwargs,
    ):
        """
        初始化 Ollama LLM 客户端

        Args:
            api_key: API 密钥（Ollama 本地部署通常为空）
            base_url: Ollama 服务地址
            model_name: 模型名称
            timeout: API 调用超时（秒）
            max_retries: 最大重试次数
            max_concurrent: 最大并发调用数
            default_system_prompt: 默认系统提示词
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model_name=model_name,
            timeout=timeout,
            max_retries=max_retries,
            max_concurrent=max_concurrent,
        )
        self.default_system_prompt = default_system_prompt
        self._http_client: Optional[httpx.AsyncClient] = None
        self._http_client_lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        """延迟创建 Lock，确保在事件循环内初始化"""
        if self._http_client_lock is None:
            self._http_client_lock = asyncio.Lock()
        return self._http_client_lock

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端（延迟初始化）"""
        async with self._get_lock():
            if self._http_client is None:
                self._http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout, connect=10.0),
                    limits=httpx.Limits(max_connections=10),
                )
        return self._http_client

    def _build_messages(self, prompt: str | list) -> list:
        """构建消息列表"""
        if isinstance(prompt, list):
            return prompt
        return [
            {"role": "system", "content": self.default_system_prompt},
            {"role": "user", "content": prompt},
        ]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError, OSError)),
        reraise=True,
    )
    async def generate_text(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        response_format: Optional[dict] = None,
        enable_thinking: bool = False,
    ) -> str:
        """
        生成文本（非流式）

        Args:
            prompt: 提示词（字符串或消息列表）
            max_tokens: 最大生成 token 数
            temperature: 温度参数
            top_p: top_p 参数

        Returns:
            生成的文本
        """
        async with self._get_semaphore():
            client = await self._get_http_client()
            messages = self._build_messages(prompt)

            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                        "top_p": top_p,
                    },
                },
            )
            response.raise_for_status()
            result = response.json()

            content = result.get("message", {}).get("content", "")

            # 记录统计信息
            eval_count = result.get("eval_count", 0)
            prompt_eval_count = result.get("prompt_eval_count", 0)
            if eval_count or prompt_eval_count:
                logger.info(
                    "Ollama LLM 调用统计",
                    model=self.model,
                    prompt_tokens=prompt_eval_count,
                    completion_tokens=eval_count,
                    total_tokens=prompt_eval_count + eval_count,
                )

            return content

    async def generate_text_stream(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        enable_thinking: bool = False,
    ) -> AsyncGenerator[str, None]:
        """
        流式生成文本

        通过 Ollama /api/chat 的 stream 模式，读取 NDJSON 响应。

        Args:
            prompt: 提示词（字符串或消息列表）
            max_tokens: 最大生成 token 数
            temperature: 温度参数
            top_p: top_p 参数

        Yields:
            str: 生成的文本片段
        """
        async with self._get_semaphore():
            client = await self._get_http_client()
            messages = self._build_messages(prompt)

            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                        "top_p": top_p,
                    },
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        logger.warning("Ollama 流式响应解析失败", line=line[:100])

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
