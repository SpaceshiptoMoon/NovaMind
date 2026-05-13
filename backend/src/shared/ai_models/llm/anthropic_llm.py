"""
Anthropic LLM 客户端

基于 Anthropic SDK，支持 Claude 系列模型。
"""

from typing import Optional, AsyncGenerator

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.shared.ai_models.base_model import BaseLLM
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class AnthropicLLM(BaseLLM):
    """
    Anthropic LLM 客户端

    使用 anthropic SDK 调用 Claude 系列模型。
    支持 Messages API 的文本生成和流式生成。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        model_name: str = "claude-sonnet-4-20250514",
        timeout: int = 120,
        max_retries: int = 3,
        max_concurrent: int = 10,
        default_max_tokens: int = 4096,
        **kwargs,
    ):
        """
        初始化 Anthropic LLM 客户端

        Args:
            api_key: Anthropic API 密钥
            base_url: API 基础 URL（默认官方地址）
            model_name: 模型名称
            timeout: API 调用超时（秒）
            max_retries: 最大重试次数
            max_concurrent: 最大并发调用数
            default_max_tokens: 默认最大生成 token 数（Anthropic 必填）
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            timeout=timeout,
            max_retries=max_retries,
            max_concurrent=max_concurrent,
        )
        self.default_max_tokens = default_max_tokens

        # 延迟导入 anthropic，避免未安装时报错
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise ImportError(
                "使用 Anthropic 协议需要安装 anthropic 库: pip install anthropic"
            )

        self.client = AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    def _build_messages(self, prompt: str | list) -> tuple:
        """
        构建 Anthropic 格式的 system_prompt 和 messages

        Anthropic 的 system prompt 是独立参数，不在 messages 中。

        Returns:
            (system_prompt, messages)
        """
        if isinstance(prompt, list):
            # 从消息列表中提取 system 消息
            system_parts = []
            messages = []
            for msg in prompt:
                if msg.get("role") == "system":
                    system_parts.append(msg["content"])
                else:
                    messages.append(msg)
            system_prompt = "\n".join(system_parts) if system_parts else None
            return system_prompt, messages
        else:
            return None, [{"role": "user", "content": prompt}]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
        reraise=True,
    )
    async def generate_text(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        response_format: Optional[dict] = None,
        top_k: Optional[int] = None,
        stop_sequences: Optional[list[str]] = None,
        enable_thinking: bool = False,
    ) -> str:
        """
        生成文本（带重试和并发控制）
        """
        async with self._get_semaphore():
            system_prompt, messages = self._build_messages(prompt)

            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens or self.default_max_tokens,
                "temperature": temperature,
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            if top_p is not None:
                kwargs["top_p"] = top_p
            if top_k is not None:
                kwargs["top_k"] = top_k
            if stop_sequences:
                kwargs["stop_sequences"] = stop_sequences

            response = await self.client.messages.create(**kwargs)

            # 记录 Token 用量
            if response.usage:
                logger.info(
                    "Anthropic 调用统计",
                    model=self.model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )

            # 提取文本内容
            content = response.content
            if content and len(content) > 0:
                return content[0].text
            return ""

    async def generate_text_stream(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        top_k: Optional[int] = None,
        stop_sequences: Optional[list[str]] = None,
        enable_thinking: bool = False,
    ) -> AsyncGenerator[str, None]:
        """
        流式生成文本（带并发控制，不使用自动重试）
        """
        async with self._get_semaphore():
            system_prompt, messages = self._build_messages(prompt)

            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens or self.default_max_tokens,
                "temperature": temperature,
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            if top_p is not None:
                kwargs["top_p"] = top_p
            if top_k is not None:
                kwargs["top_k"] = top_k
            if stop_sequences:
                kwargs["stop_sequences"] = stop_sequences

            async with self.client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text

    async def close(self) -> None:
        """关闭 Anthropic 客户端连接"""
        await self.client.close()
