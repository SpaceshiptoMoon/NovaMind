"""
Anthropic LLM 客户端

基于 Anthropic SDK，支持 Claude 系列模型。
"""

import json
from collections.abc import AsyncGenerator
from typing import Any

from novamind.shared.ai_models.base_model import (
    BaseLLM,
    LLMCapabilities,
    LLMResponse,
    LLMResponseWithTools,
    StreamChunk,
    ToolCall,
    ToolStreamEvent,
)
from novamind.shared.ai_models.errors import translate_provider_error
from novamind.shared.ai_models.llm.quirks import LLMQuirks
from novamind.shared.logging import get_logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = get_logger(__name__)


class AnthropicLLM(BaseLLM):
    """
    Anthropic LLM 客户端

    使用 anthropic SDK 调用 Claude 系列模型。
    支持 Messages API 的文本生成和流式生成。
    """

    # Anthropic Messages API 原生支持工具调用与 extended thinking。
    capabilities = LLMCapabilities(tools=True, thinking=True)

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        model_name: str = "claude-sonnet-4-20250514",
        timeout: int = 120,
        max_retries: int = 3,
        max_concurrent: int = 10,
        default_max_tokens: int = 4096,
        quirks: LLMQuirks | None = None,
        **kwargs,
    ):
        """
        初始化 Anthropic LLM 客户端

        Args:
            api_key: 凭据本体（API Key 或 Bearer token，按 quirks.auth_type 决定发送头）
            base_url: API 基础 URL（默认官方地址）
            model_name: 模型名称
            timeout: API 调用超时（秒）
            max_retries: 最大重试次数
            max_concurrent: 最大并发调用数
            default_max_tokens: 默认最大生成 token 数（Anthropic 必填）
            quirks: provider 怪癖声明；auth_type 决定凭据走 x-api-key 还是
                Authorization: Bearer 头，None 时按官方语义走 x-api-key
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
        self.quirks = quirks or LLMQuirks()

        # 延迟导入 anthropic，避免未安装时报错
        try:
            from anthropic import AsyncAnthropic, Omit
        except ImportError:
            raise ImportError(
                "使用 Anthropic 协议需要安装 anthropic 库: pip install anthropic"
            )

        # 凭据只认显式传入的值。不传的槽位必须用 Omit 压头：auth_token/api_key
        # 缺省时 SDK 会自动读宿主环境 ANTHROPIC_AUTH_TOKEN / ANTHROPIC_API_KEY，
        # 双头并发；优先校验 Authorization 的网关（如智谱）会用环境里的无关
        # token 鉴权而 401。
        client_kwargs: dict = {
            # 空串/None 一律落官方默认：传 None 时 SDK 会回读宿主环境
            # ANTHROPIC_BASE_URL，把请求劫持到无关端点
            "base_url": self.base_url or "https://api.anthropic.com",
            "timeout": timeout,
            "max_retries": max_retries,
        }
        if self.quirks.auth_type == "bearer":
            client_kwargs["auth_token"] = self.api_key
            client_kwargs["api_key"] = ""
            client_kwargs["default_headers"] = {"X-Api-Key": Omit()}
        else:
            client_kwargs["api_key"] = self.api_key
            client_kwargs["auth_token"] = ""
            client_kwargs["default_headers"] = {"Authorization": Omit()}
        self.client = AsyncAnthropic(**client_kwargs)

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

    @staticmethod
    def _convert_tools(tools: list[dict]) -> list[dict]:
        """OpenAI function calling 格式 → Anthropic tools 格式。

        {"type":"function","function":{name,description,parameters}} →
        {"name","description","input_schema":parameters}。

        Args:
            tools: OpenAI 格式工具定义列表。

        Returns:
            Anthropic 格式工具定义列表。
        """
        converted = []
        for tool in tools:
            func = tool.get("function") or {}
            converted.append({
                "name": func.get("name") or tool.get("name", ""),
                "description": func.get("description") or tool.get("description", ""),
                "input_schema": func.get("parameters") or {"type": "object", "properties": {}},
            })
        return converted

    @staticmethod
    def _convert_messages(messages: list[dict]) -> list[dict]:
        """OpenAI 内部消息格式 → Anthropic messages 参数格式。

        转换规则：
        - assistant.tool_calls → content 中的 tool_use 块（原 text 内容保留为 text 块）
        - role="tool" 结果消息 → user 消息中的 tool_result 块；连续多条结果消息
          必须合并为一条 user 消息（Anthropic 硬约束：tool_result 须紧跟对应
          tool_use 的 user 回合，引擎正是逐条 append 多个工具结果）。

        Args:
            messages: OpenAI 格式消息列表（不含 system，调用前经 _build_messages 提取）。

        Returns:
            Anthropic 格式消息列表。
        """
        converted: list[dict] = []
        pending_results: list[dict] = []

        def flush_results() -> None:
            if pending_results:
                converted.append({"role": "user", "content": list(pending_results)})
                pending_results.clear()

        for msg in messages:
            role = msg.get("role")
            if role == "tool":
                content = msg.get("content")
                pending_results.append({
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                })
                continue

            flush_results()
            if role == "assistant":
                blocks: list[dict] = []
                text = msg.get("content")
                if text:
                    blocks.append({"type": "text", "text": text})
                for tc in msg.get("tool_calls") or []:
                    func = tc.get("function") or {}
                    raw_args = func.get("arguments") or "{}"
                    try:
                        tool_input = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        tool_input = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "input": tool_input,
                    })
                if blocks:
                    converted.append({"role": "assistant", "content": blocks})
            else:
                converted.append({"role": role or "user", "content": msg.get("content") or ""})

        flush_results()
        return converted

    @staticmethod
    def _map_stop_reason(stop_reason: str | None) -> str:
        """Anthropic stop_reason → OpenAI finish_reason 语义。"""
        return {"tool_use": "tool_calls", "stop_sequence": "stop"}.get(stop_reason or "", "stop")

    @staticmethod
    def _normalize_usage(usage: Any) -> dict[str, int] | None:
        """Anthropic usage → 统一 usage 字典（缓存读写 token 单列）。"""
        if usage is None:
            return None
        return {
            "prompt_tokens": getattr(usage, "input_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "output_tokens", 0) or 0,
            "total_tokens": (getattr(usage, "input_tokens", 0) or 0)
            + (getattr(usage, "output_tokens", 0) or 0),
            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        }

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
        response_format: dict | None = None,
        top_k: int | None = None,
        stop_sequences: list[str] | None = None,
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

            # 提取文本内容：只取 text 块。思考型模型（如智谱 glm-5.3-flash 经
            # Anthropic 兼容端点）content 首块恒为 thinking 块且不可关闭，取
            # content[0].text 会在 ThinkingBlock 上抛 AttributeError
            text = "".join(
                block.text for block in response.content if getattr(block, "type", None) == "text"
            )
            if not text:
                # 空正文告警：stop_reason=max_tokens 时通常是思考 token 耗尽预算
                # （思考不可关的模型），对齐 openai_compatible 空 content 告警先例，
                # 调用方据此调大预算或换非思考模型。
                usage = response.usage
                logger.warning(
                    "Anthropic 响应无 text 块（疑似思考 token 耗尽 max_tokens）",
                    model=self.model,
                    max_tokens=kwargs["max_tokens"],
                    output_tokens=getattr(usage, "output_tokens", None),
                    stop_reason=response.stop_reason,
                )
            return text

    async def generate_text_stream(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        top_k: int | None = None,
        stop_sequences: list[str] | None = None,
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
        """支持工具调用的非流式文本生成。

        Args:
            prompt: 提示词文本或 OpenAI 格式消息列表。
            tools: OpenAI 格式工具定义列表；空表示不启用工具。
            max_tokens: 最大生成 token 数。
            temperature: 采样温度。
            top_p: 核采样概率上限。
            tool_choice: 工具选择策略（auto/none），仅 auto/none 生效。
            enable_thinking: 是否启用 extended thinking。

        Returns:
            LLMResponseWithTools，reasoning 字段承载 thinking 块文本。

        Raises:
            ModelProviderError: 服务商返回错误（经统一异常翻译）。
        """
        async with self._get_semaphore():
            system_prompt, messages = self._build_messages(prompt)
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": self._convert_messages(messages),
                "max_tokens": max_tokens or self.default_max_tokens,
                "temperature": temperature,
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            if top_p is not None:
                kwargs["top_p"] = top_p
            if tools:
                kwargs["tools"] = self._convert_tools(tools)
            if enable_thinking:
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": max(1024, max_tokens // 2)}

            try:
                response = await self.client.messages.create(**kwargs)
            except Exception as e:
                logger.warning("Anthropic 工具调用请求失败", model=self.model, error=str(e)[:200])
                raise translate_provider_error(e, model=self.model) from e

            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls: list[ToolCall] = []
            for block in response.content:
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    text_parts.append(block.text)
                elif block_type == "thinking":
                    reasoning_parts.append(getattr(block, "thinking", ""))
                elif block_type == "tool_use":
                    tool_calls.append(ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=json.dumps(block.input, ensure_ascii=False),
                    ))

            usage = self._normalize_usage(response.usage)
            if usage:
                logger.info(
                    "Anthropic 工具调用统计",
                    model=self.model,
                    tool_calls=len(tool_calls),
                    stop_reason=response.stop_reason,
                    prompt_tokens=usage["prompt_tokens"],
                    completion_tokens=usage["completion_tokens"],
                )

            return LLMResponseWithTools(
                content="".join(text_parts) or None,
                tool_calls=tool_calls or None,
                finish_reason=self._map_stop_reason(response.stop_reason),
                usage=usage,
                reasoning="".join(reasoning_parts) or None,
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
        """支持工具调用的流式生成（messages.stream 事件流 → ToolStreamEvent）。

        事件映射：text_delta→content、thinking_delta→reasoning、
        tool_use 块的 input_json_delta 累积后→tool_call_start/args/end、
        message_delta 的 stop_reason=tool_use→finish_reason=tool_calls。
        约束：tool_call_end 先于 done 产出。
        """
        async with self._get_semaphore():
            system_prompt, messages = self._build_messages(prompt)
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": self._convert_messages(messages),
                "max_tokens": max_tokens or self.default_max_tokens,
                "temperature": temperature,
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            if top_p is not None:
                kwargs["top_p"] = top_p
            if tools:
                kwargs["tools"] = self._convert_tools(tools)
            if enable_thinking:
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": max(1024, max_tokens // 2)}

            active_tools: dict[int, dict] = {}
            usage_data: dict[str, int] | None = None
            finish_reason = "stop"

            try:
                async with self.client.messages.stream(**kwargs) as stream:
                    async for event in stream:
                        etype = event.type
                        if etype == "message_start":
                            usage_data = self._normalize_usage(
                                getattr(event.message, "usage", None)
                            )
                        elif etype == "content_block_start":
                            block = event.content_block
                            if getattr(block, "type", None) == "tool_use":
                                active_tools[event.index] = {
                                    "id": block.id,
                                    "name": block.name,
                                    "arguments": "",
                                }
                                yield ToolStreamEvent(
                                    type="tool_call_start",
                                    tool_call_id=block.id,
                                    tool_name=block.name,
                                )
                        elif etype == "content_block_delta":
                            delta = event.delta
                            delta_type = getattr(delta, "type", None)
                            if delta_type == "text_delta":
                                yield ToolStreamEvent(type="content", content=delta.text)
                            elif delta_type == "thinking_delta":
                                yield ToolStreamEvent(type="reasoning", content=delta.thinking)
                            elif delta_type == "input_json_delta":
                                tc = active_tools.get(event.index)
                                if tc is not None:
                                    tc["arguments"] += delta.partial_json
                                    yield ToolStreamEvent(
                                        type="tool_call_args",
                                        tool_call_id=tc["id"],
                                        tool_arguments_delta=delta.partial_json,
                                    )
                        elif etype == "content_block_stop":
                            tc = active_tools.pop(event.index, None)
                            if tc is not None:
                                yield ToolStreamEvent(
                                    type="tool_call_end",
                                    tool_call_id=tc["id"],
                                    tool_name=tc["name"],
                                    tool_arguments_delta=tc["arguments"],
                                )
                        elif etype == "message_delta":
                            delta_usage = self._normalize_usage(event.usage)
                            if delta_usage:
                                usage_data = {
                                    **(usage_data or {}),
                                    "completion_tokens": delta_usage["completion_tokens"],
                                    "total_tokens": (
                                        (usage_data or {}).get("prompt_tokens", 0)
                                        + delta_usage["completion_tokens"]
                                    ),
                                    "cache_read_tokens": delta_usage.get("cache_read_tokens", 0),
                                    "cache_write_tokens": delta_usage.get("cache_write_tokens", 0),
                                }
                            if event.delta.stop_reason == "tool_use":
                                finish_reason = "tool_calls"
            except Exception as e:
                logger.warning("Anthropic 工具流式请求失败", model=self.model, error=str(e)[:200])
                raise translate_provider_error(e, model=self.model) from e

            yield ToolStreamEvent(
                type="done", usage=usage_data, finish_reason=finish_reason,
            )

    async def generate_text_structured(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        response_format: dict[str, Any] | None = None,
        enable_thinking: bool = False,
    ) -> LLMResponse:
        """非流式结构化生成：thinking 块提取为 reasoning 字段。"""
        async with self._get_semaphore():
            system_prompt, messages = self._build_messages(prompt)
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": self._convert_messages(messages),
                "max_tokens": max_tokens or self.default_max_tokens,
                "temperature": temperature,
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            if top_p is not None:
                kwargs["top_p"] = top_p
            if enable_thinking:
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": max(1024, max_tokens // 2)}

            try:
                response = await self.client.messages.create(**kwargs)
            except Exception as e:
                raise translate_provider_error(e, model=self.model) from e

            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            for block in response.content:
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    text_parts.append(block.text)
                elif block_type == "thinking":
                    reasoning_parts.append(getattr(block, "thinking", ""))
            return LLMResponse(content="".join(text_parts), reasoning="".join(reasoning_parts) or None)

    async def generate_text_stream_structured(
        self,
        prompt: str | list,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.8,
        enable_thinking: bool = False,
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式结构化生成：thinking_delta→reasoning 块、text_delta→content 块。"""
        async with self._get_semaphore():
            system_prompt, messages = self._build_messages(prompt)
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": self._convert_messages(messages),
                "max_tokens": max_tokens or self.default_max_tokens,
                "temperature": temperature,
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            if top_p is not None:
                kwargs["top_p"] = top_p
            if enable_thinking:
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": max(1024, max_tokens // 2)}

            try:
                async with self.client.messages.stream(**kwargs) as stream:
                    async for event in stream:
                        if event.type != "content_block_delta":
                            continue
                        delta = event.delta
                        delta_type = getattr(delta, "type", None)
                        if delta_type == "text_delta":
                            yield StreamChunk(type="content", text=delta.text)
                        elif delta_type == "thinking_delta":
                            yield StreamChunk(type="reasoning", text=delta.thinking)
            except Exception as e:
                raise translate_provider_error(e, model=self.model) from e

    async def close(self) -> None:
        """关闭 Anthropic 客户端连接"""
        await self.client.close()
