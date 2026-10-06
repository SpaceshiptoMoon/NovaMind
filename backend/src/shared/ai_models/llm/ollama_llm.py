"""
Ollama 原生 LLM 客户端

使用 Ollama 原生 /api/chat 端点，支持文本生成和流式生成。
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from novamind.shared.ai_models.base_model import (
    BaseLLM,
    LLMCapabilities,
    LLMResponseWithTools,
    ToolCall,
)
from novamind.shared.ai_models.errors import translate_provider_error
from novamind.shared.logging import get_logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = get_logger(__name__)


class OllamaLLM(BaseLLM):
    """
    Ollama 原生 LLM 客户端

    通过 Ollama 原生 API (/api/chat) 进行文本生成。
    默认 base_url: http://localhost:11434
    """

    # Ollama /api/chat 支持非流式 tools（0.3+ 模型侧支持不等，缺能力由模型报错），
    # 思考模式不透传（enable_thinking 非该 API 字段）；流式工具不做（上层
    # AgentLLM 捕获 NotImplementedError 降级非流式）。
    capabilities = LLMCapabilities(tools=True, thinking=False)

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
        self._http_client: httpx.AsyncClient | None = None
        self._http_client_lock: asyncio.Lock | None = None

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
        response_format: dict | None = None,
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
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise translate_provider_error(e, model=self.model) from e
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
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    raise translate_provider_error(e, model=self.model) from e
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
        """支持工具调用的非流式文本生成（/api/chat 原生 tools）。

        OpenAI 格式工具定义转 Ollama 格式（function 外壳去掉一层）；响应的
        tool_calls[].function.arguments 是 dict，归一为 JSON 字符串。

        Args:
            prompt: 提示词（字符串或消息列表）。
            tools: OpenAI function calling 格式工具定义；空表示不启用。
            max_tokens: 最大生成 token 数。
            temperature: 采样温度。
            top_p: 核采样概率上限。
            tool_choice: Ollama 无此参数，忽略。
            enable_thinking: Ollama /api/chat 无对应字段，忽略。

        Returns:
            LLMResponseWithTools，含正文、归一化 tool_calls、finish_reason 与 usage。

        Raises:
            ModelProviderError: 服务端返回错误（经统一异常翻译）。
        """
        async with self._get_semaphore():
            client = await self._get_http_client()
            messages = self._build_messages(prompt)

            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p,
                },
            }
            if tools:
                payload["tools"] = [
                    (tool.get("function") or tool) for tool in tools
                ]

            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                # httpx 异常文本不含响应体，而 Ollama 的错误详情（含计费类词面）
                # 在 body 里——拼接后翻译，额度/欠费类语义检测才有判据
                body_snippet = (response.text or "")[:300]
                wrapped = type(e)(f"{e}\n{body_snippet}", request=e.request, response=e.response)
                raise translate_provider_error(wrapped, model=self.model) from e
            result = response.json()

            message = result.get("message", {})
            tool_calls = [
                ToolCall(
                    id=tc.get("id") or f"call_{idx}",
                    name=(tc.get("function") or {}).get("name", ""),
                    arguments=json.dumps(
                        (tc.get("function") or {}).get("arguments") or {},
                        ensure_ascii=False,
                    ),
                )
                for idx, tc in enumerate(message.get("tool_calls") or [])
            ]

            usage = None
            eval_count = result.get("eval_count", 0)
            prompt_eval_count = result.get("prompt_eval_count", 0)
            if eval_count or prompt_eval_count:
                usage = {
                    "prompt_tokens": prompt_eval_count,
                    "completion_tokens": eval_count,
                    "total_tokens": prompt_eval_count + eval_count,
                }
                logger.info(
                    "Ollama 工具调用统计",
                    model=self.model,
                    tool_calls=len(tool_calls),
                    prompt_tokens=prompt_eval_count,
                    completion_tokens=eval_count,
                )

            return LLMResponseWithTools(
                content=message.get("content") or None,
                tool_calls=tool_calls or None,
                finish_reason="tool_calls" if tool_calls else "stop",
                usage=usage,
            )

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
