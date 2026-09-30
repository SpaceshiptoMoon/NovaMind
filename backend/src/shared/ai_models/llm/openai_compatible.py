"""
OpenAI 兼容 LLM 客户端

基于 OpenAI SDK，覆盖所有兼容 OpenAI API 的服务商：
OpenAI、智谱 AI、阿里云 DashScope、硅基流动、本地 vLLM/Ollama 等
"""

import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from novamind.shared.ai_models.base_model import (
    BaseLLM,
    LLMResponse,
    LLMResponseWithTools,
    StreamChunk,
    ToolCall,
    ToolStreamEvent,
    build_openai_http_client,
)
from novamind.shared.ai_models.embedding.openai_compatible import OPENAI_RETRY_EXCEPTIONS
from novamind.shared.logging import get_logger
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = get_logger(__name__)


class OpenAICompatibleLLM(BaseLLM):
    """
    OpenAI 兼容 LLM 客户端

    通过配置不同的 api_key / base_url / model_name 适配各种 OpenAI 兼容服务商。
    支持文本生成和流式生成。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout: int = 120,
        max_retries: int = 3,
        max_concurrent: int = 10,
        default_system_prompt: str = "You are a helpful assistant.",
        prompt_cache_key: str | None = None,
        **kwargs,
    ):
        """
        初始化 OpenAI 兼容 LLM 客户端

        Args:
            api_key: API 密钥
            base_url: API 基础 URL
            model_name: 模型名称
            timeout: API 调用超时（秒）
            max_retries: 最大重试次数
            max_concurrent: 最大并发调用数
            default_system_prompt: 默认系统提示词
            prompt_cache_key: OpenAI prompt caching 路由键，可空。非空时注入请求
                extra_body.prompt_cache_key，引导服务端把同键请求路由到同缓存分片，
                提高 prompt cache 命中率（官方口径：相同前缀 + 相同 cache key 才稳定
                命中；对不支持该字段的自建/第三方网关，多传字段通常被忽略，无害）。
                构造链从用户模型配置 extra_config 读取：布尔 true → 按模型名生成
                稳定键，字符串 → 字面量键（见 model_config_service）。
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            timeout=timeout,
            max_retries=max_retries,
            max_concurrent=max_concurrent,
        )
        self.default_system_prompt = default_system_prompt
        self._prompt_cache_key = prompt_cache_key

        # OpenAI 客户端：禁用 SDK 内置重试，由 tenacity 统一管理重试。
        http_client = build_openai_http_client(
            timeout=timeout,
            max_connections=max_concurrent * 2,
        )
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            http_client=http_client,
            timeout=httpx.Timeout(timeout, connect=10.0),
            max_retries=0,
        )

    def _build_messages(self, prompt: str | list) -> list:
        """构建消息列表"""
        if isinstance(prompt, list):
            return prompt
        return [
            {"role": "system", "content": self.default_system_prompt},
            {"role": "user", "content": prompt},
        ]

    def _apply_prompt_cache_key(self, extra_body: dict) -> None:
        """向请求 extra_body 注入 prompt_cache_key（配置了才注入）。

        Args:
            extra_body: 各请求方法已构造的 extra_body dict，原地追加。
        """
        if self._prompt_cache_key:
            extra_body["prompt_cache_key"] = self._prompt_cache_key

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError)
            + OPENAI_RETRY_EXCEPTIONS,
        ),
        reraise=True,
    )
    async def generate_text(
        self,
        prompt: str | list,
        max_tokens: int = 16384,
        temperature: float = 0.7,
        top_p: float = 0.8,
        response_format: dict | None = None,
        enable_thinking: bool = False,
    ) -> str:
        """
        生成文本（带重试和并发控制）
        """
        async with self._get_semaphore():
            messages = self._build_messages(prompt)
            prompt_len = len(str(prompt)[:500])

            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
            }
            if response_format:
                kwargs["response_format"] = response_format
            kwargs["extra_body"] = {"enable_thinking": enable_thinking}
            self._apply_prompt_cache_key(kwargs["extra_body"])

            logger.info(
                "LLM 请求开始",
                model=self.model,
                prompt_length=prompt_len,
                max_tokens=max_tokens,
                timeout=self.timeout,
            )
            start_time = time.monotonic()

            try:
                response = await self.client.chat.completions.create(**kwargs)
            except Exception as e:
                elapsed = time.monotonic() - start_time
                logger.warning(
                    "LLM 请求失败",
                    model=self.model,
                    error_type=type(e).__name__,
                    error=str(e)[:200],
                    elapsed_s=round(elapsed, 1),
                    timeout=self.timeout,
                )
                raise

            elapsed = time.monotonic() - start_time

            # 记录 Token 用量
            if response.usage:
                logger.info(
                    "LLM 调用统计",
                    model=self.model,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                    elapsed_s=round(elapsed, 1),
                )
            else:
                logger.info(
                    "LLM 请求完成（无 usage）",
                    model=self.model,
                    elapsed_s=round(elapsed, 1),
                )

            content = response.choices[0].message.content
            return content if content is not None else ""

    async def generate_text_stream(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float | None = 0.8,
        enable_thinking: bool = False,
    ) -> AsyncGenerator[str, None]:
        """
        流式生成文本（带并发控制，不使用自动重试）

        SSE 场景下不允许自动重试，否则会产生重复数据。
        """
        async with self._get_semaphore():
            messages = self._build_messages(prompt)
            prompt_len = len(str(prompt)[:500])

            logger.info(
                "LLM 流式请求开始",
                model=self.model,
                prompt_length=prompt_len,
                max_tokens=max_tokens,
            )
            start_time = time.monotonic()
            content_yielded = False

            try:
                create_kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "max_completion_tokens": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p,
                    "stream": True,
                }
                create_kwargs["extra_body"] = {"enable_thinking": enable_thinking}
                self._apply_prompt_cache_key(create_kwargs["extra_body"])
                stream = await self.client.chat.completions.create(**create_kwargs)
            except Exception as e:
                elapsed = time.monotonic() - start_time
                logger.warning(
                    "LLM 流式请求失败",
                    model=self.model,
                    error_type=type(e).__name__,
                    error=str(e)[:200],
                    elapsed_s=round(elapsed, 1),
                )
                raise

            async with stream:
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content_yielded = True
                        yield chunk.choices[0].delta.content

            elapsed = time.monotonic() - start_time
            if not content_yielded:
                logger.warning(
                    "LLM 流式响应无内容（可能模型开启了 thinking 模式）",
                    model=self.model,
                    elapsed_s=round(elapsed, 1),
                )

    # ==================== Thinking 模式适配层覆写 ====================

    async def generate_text_structured(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        response_format: dict | None = None,
        enable_thinking: bool = False,
    ) -> LLMResponse:
        """非流式结构化生成——提取 reasoning_content。

        Args:
            prompt: 提示词文本或消息列表。
            max_tokens: 最大生成 token 数。
            temperature: 采样温度。
            top_p: 核采样概率上限。
            response_format: 响应格式约束（如 JSON mode 声明）；None 表示不约束。
            enable_thinking: 是否启用模型 thinking 模式（经 extra_body 透传）。

        Returns:
            LLMResponse，content 为正文，reasoning 为思维链文本（模型未返回时为 None）。
        """
        async with self._get_semaphore():
            messages = self._build_messages(prompt)

            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
            }
            if response_format:
                kwargs["response_format"] = response_format
            kwargs["extra_body"] = {"enable_thinking": enable_thinking}
            self._apply_prompt_cache_key(kwargs["extra_body"])

            start_time = time.monotonic()
            try:
                response = await self.client.chat.completions.create(**kwargs)
            except Exception as e:
                elapsed = time.monotonic() - start_time
                logger.warning("LLM 请求失败", model=self.model, error=str(e)[:200], elapsed_s=round(elapsed, 1))
                raise

            msg = response.choices[0].message
            reasoning = getattr(msg, 'reasoning_content', None) or None
            content = msg.content if msg.content is not None else ""

            if response.usage:
                logger.info(
                    "LLM 调用统计",
                    model=self.model,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                    has_reasoning=reasoning is not None,
                )

            return LLMResponse(content=content, reasoning=reasoning)

    async def generate_text_stream_structured(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        enable_thinking: bool = False,
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式结构化生成——分离 reasoning_content 和 content。

        Args:
            prompt: 提示词文本或消息列表。
            max_tokens: 最大生成 token 数。
            temperature: 采样温度。
            top_p: 核采样概率上限。
            enable_thinking: 是否启用模型 thinking 模式。

        Returns:
            异步生成器，逐块产出 StreamChunk（type 为 reasoning 或 content）。
        """
        async with self._get_semaphore():
            messages = self._build_messages(prompt)

            logger.info(
                "LLM 流式请求开始（structured）",
                model=self.model,
                max_tokens=max_tokens,
                enable_thinking=enable_thinking,
            )

            create_kwargs = {
                "model": self.model,
                "messages": messages,
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "stream": True,
                "extra_body": {"enable_thinking": enable_thinking},
            }
            self._apply_prompt_cache_key(create_kwargs["extra_body"])

            try:
                stream = await self.client.chat.completions.create(**create_kwargs)
            except Exception as e:
                logger.warning("LLM 流式请求失败", model=self.model, error=str(e)[:200])
                raise

            has_reasoning = False
            has_content = False
            async with stream:
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    rc = getattr(delta, 'reasoning_content', None)
                    if rc:
                        has_reasoning = True
                        yield StreamChunk(type="reasoning", text=rc)
                    if delta.content:
                        has_content = True
                        yield StreamChunk(type="content", text=delta.content)

            if not has_content and not has_reasoning:
                logger.warning("LLM 流式响应无内容", model=self.model)

    async def close(self) -> None:
        """关闭 OpenAI 客户端连接"""
        await self.client.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError)
            + OPENAI_RETRY_EXCEPTIONS,
        ),
        reraise=True,
    )
    async def generate_with_tools(
        self,
        prompt: str | list,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.8,
        tool_choice: str = "auto",
        enable_thinking: bool = False,
    ) -> LLMResponseWithTools:
        """支持工具调用的非流式文本生成（带重试）。

        Args:
            prompt: 提示词文本或消息列表。
            tools: OpenAI tools 格式的工具定义列表；None 或空表示不启用工具。
            max_tokens: 最大生成 token 数。
            temperature: 采样温度。
            top_p: 核采样概率上限。
            tool_choice: 工具选择策略（auto/none/指定函数名），默认 auto。
            enable_thinking: 是否启用模型 thinking 模式。

        Returns:
            LLMResponseWithTools，含正文、解析后的 tool_calls、finish_reason 与 usage。
        """
        async with self._get_semaphore():
            messages = self._build_messages(prompt)

            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice
            kwargs["extra_body"] = {"enable_thinking": enable_thinking}
            self._apply_prompt_cache_key(kwargs["extra_body"])

            response = await self.client.chat.completions.create(**kwargs)

            choice = response.choices[0]

            # 解析工具调用
            tool_calls = None
            if choice.message.tool_calls:
                tool_calls = [
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=tc.function.arguments,
                    )
                    for tc in choice.message.tool_calls
                ]

            # 记录 Token 用量
            usage = None
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
                logger.info(
                    "LLM 工具调用统计",
                    model=self.model,
                    has_tool_calls=tool_calls is not None,
                    finish_reason=choice.finish_reason,
                    prompt_tokens=usage["prompt_tokens"],
                    completion_tokens=usage["completion_tokens"],
                    total_tokens=usage["total_tokens"],
                )

            return LLMResponseWithTools(
                content=choice.message.content,
                tool_calls=tool_calls,
                finish_reason=choice.finish_reason or "stop",
                usage=usage,
                reasoning=getattr(choice.message, 'reasoning_content', None),
            )

    async def generate_with_tools_stream(
        self,
        prompt: str | list,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.8,
        tool_choice: str = "auto",
        enable_thinking: bool = False,
    ) -> AsyncGenerator[ToolStreamEvent, None]:
        """支持工具调用的原生流式生成（OpenAI SDK stream=True + tools）。

        逐 chunk 解析 content 增量与 tool_calls 增量，自动收集完整工具调用参数，
        以 ToolStreamEvent 形式 yield。上层（AgentLLM）翻译为自有 StreamChunk。
        """
        async with self._get_semaphore():
            messages = self._build_messages(prompt)
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice
            kwargs["extra_body"] = {"enable_thinking": enable_thinking}
            self._apply_prompt_cache_key(kwargs["extra_body"])

            stream = await self.client.chat.completions.create(**kwargs)

            # 收集器：index -> {id, name, arguments}
            active_tool_calls: dict[int, dict] = {}

            async for chunk in stream:
                # usage-only chunk（最后一个 chunk 可能只有 usage）
                if not chunk.choices:
                    if hasattr(chunk, "usage") and chunk.usage:
                        yield ToolStreamEvent(
                            type="done",
                            usage={
                                "prompt_tokens": chunk.usage.prompt_tokens or 0,
                                "completion_tokens": chunk.usage.completion_tokens or 0,
                                "total_tokens": chunk.usage.total_tokens or 0,
                            },
                        )
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # 文本内容增量
                if delta.content:
                    yield ToolStreamEvent(type="content", content=delta.content)

                # 工具调用增量
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index

                        # 新工具调用开始
                        if idx not in active_tool_calls:
                            call_id = tc_delta.id or f"call_{idx}"
                            active_tool_calls[idx] = {
                                "id": call_id,
                                "name": "",
                                "arguments": "",
                            }

                        tc = active_tool_calls[idx]

                        if tc_delta.id:
                            tc["id"] = tc_delta.id

                        if tc_delta.function:
                            if tc_delta.function.name:
                                tc["name"] = tc_delta.function.name
                                yield ToolStreamEvent(
                                    type="tool_call_start",
                                    tool_call_id=tc["id"],
                                    tool_name=tc["name"],
                                )
                            if tc_delta.function.arguments:
                                tc["arguments"] += tc_delta.function.arguments
                                yield ToolStreamEvent(
                                    type="tool_call_args",
                                    tool_call_id=tc["id"],
                                    tool_arguments_delta=tc_delta.function.arguments,
                                )

                # finish_reason 标记结束
                if choice.finish_reason:
                    for i in sorted(active_tool_calls.keys()):
                        tc = active_tool_calls[i]
                        yield ToolStreamEvent(
                            type="tool_call_end",
                            tool_call_id=tc["id"],
                            tool_name=tc["name"],
                            tool_arguments_delta=tc["arguments"],
                        )

                    yield ToolStreamEvent(
                        type="done",
                        finish_reason=choice.finish_reason,
                    )
