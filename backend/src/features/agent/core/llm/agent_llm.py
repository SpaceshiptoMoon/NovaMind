"""
Agent 专用 LLM 封装

组合持有 BaseLLM 实例（而非继承），提供 Agent 友好的接口：
- generate(): 非流式生成（委托给 BaseLLM）
- generate_stream(): 真正的流式输出（OpenAI SDK 原生流式 + 降级策略）

选择组合而非继承的理由：
- BaseLLM 是 shared 层通用抽象，不应被 Agent 专用需求污染
- Agent 特有的流式工具调用逻辑封装在 feature 层
"""
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from novamind.shared.ai_models.base_model import BaseLLM
from novamind.shared.ai_models.llm.openai_compatible import OpenAICompatibleLLM
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class StreamChunk:
    """
    流式输出块

    类型说明：
    - content: 文本内容增量
    - tool_call_start: 检测到工具调用开始，产出 tool_call_id 和 tool_name
    - tool_call_args: 工具参数的增量 chunk
    - tool_call_end: 一个工具调用完成，参数拼接完毕
    - done: 全部完成，附带 usage 统计
    """

    type: str  # content / tool_call_start / tool_call_args / tool_call_end / done
    content: str = ""
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments_delta: str = ""
    usage: Optional[Dict[str, int]] = None
    finish_reason: Optional[str] = None


@dataclass
class CollectedToolCall:
    """收集完整的工具调用"""
    id: str
    name: str
    arguments: str


@dataclass
class AgentLLMResponse:
    """AgentLLM 的完整响应"""
    content: str = ""
    tool_calls: List[CollectedToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: Optional[Dict[str, int]] = None


class AgentLLM:
    """
    Agent 专用 LLM 封装

    职责：
    1. 封装 BaseLLM，提供 Agent 友好的接口
    2. 支持真正的流式输出（逐 token 产出）
    3. 流式场景下的工具调用收集
    4. Token 使用量聚合
    """

    def __init__(self, base_llm: BaseLLM):
        self._llm = base_llm

    @property
    def model_name(self) -> str:
        return self._llm.model

    @property
    def base_llm(self) -> BaseLLM:
        return self._llm

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.8,
        tool_choice: str = "auto",
    ) -> AgentLLMResponse:
        """
        非流式生成

        直接委托给 BaseLLM.generate_with_tools()
        """
        response = await self._llm.generate_with_tools(
            prompt=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            tool_choice=tool_choice,
        )
        return AgentLLMResponse(
            content=response.content or "",
            tool_calls=[
                CollectedToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)
                for tc in (response.tool_calls or [])
            ],
            finish_reason=response.finish_reason,
            usage=response.usage,
        )

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.8,
        tool_choice: str = "auto",
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        流式生成

        OpenAI 兼容客户端：使用 stream=True + tools 原生流式
        其他 LLM：降级为非流式
        """
        if isinstance(self._llm, OpenAICompatibleLLM):
            async for chunk in self._stream_with_tools_openai(
                messages, tools, max_tokens, temperature, top_p, tool_choice
            ):
                yield chunk
        else:
            async for chunk in self._stream_fallback(
                messages, tools, max_tokens, temperature, top_p, tool_choice
            ):
                yield chunk

    async def _stream_with_tools_openai(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        max_tokens: int,
        temperature: float,
        top_p: float,
        tool_choice: str,
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        基于 OpenAI SDK 的流式工具调用

        逐 chunk 解析 content 和 tool_calls 的增量，
        自动收集完整的工具调用参数。
        """
        async with self._llm._get_semaphore():
            kwargs: Dict[str, Any] = {
                "model": self._llm.model,
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

            stream = await self._llm.client.chat.completions.create(**kwargs)

            # 收集器：index -> CollectedToolCall
            active_tool_calls: Dict[int, CollectedToolCall] = {}

            async for chunk in stream:
                # usage-only chunk（最后一个 chunk 可能只有 usage）
                if not chunk.choices:
                    if hasattr(chunk, "usage") and chunk.usage:
                        yield StreamChunk(
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
                    yield StreamChunk(type="content", content=delta.content)

                # 工具调用增量
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index

                        # 新工具调用开始
                        if idx not in active_tool_calls:
                            call_id = tc_delta.id or f"call_{idx}"
                            active_tool_calls[idx] = CollectedToolCall(
                                id=call_id, name="", arguments=""
                            )

                        tc = active_tool_calls[idx]

                        if tc_delta.id:
                            tc.id = tc_delta.id

                        if tc_delta.function:
                            if tc_delta.function.name:
                                tc.name = tc_delta.function.name
                                yield StreamChunk(
                                    type="tool_call_start",
                                    tool_call_id=tc.id,
                                    tool_name=tc.name,
                                )
                            if tc_delta.function.arguments:
                                tc.arguments += tc_delta.function.arguments
                                yield StreamChunk(
                                    type="tool_call_args",
                                    tool_call_id=tc.id,
                                    tool_arguments_delta=tc_delta.function.arguments,
                                )

                # finish_reason 标记结束
                if choice.finish_reason:
                    # 发送所有工具调用的完成事件
                    for idx in sorted(active_tool_calls.keys()):
                        tc = active_tool_calls[idx]
                        yield StreamChunk(
                            type="tool_call_end",
                            tool_call_id=tc.id,
                            tool_name=tc.name,
                            tool_arguments_delta=tc.arguments,
                        )

                    yield StreamChunk(
                        type="done",
                        finish_reason=choice.finish_reason,
                    )

    async def _stream_fallback(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        max_tokens: int,
        temperature: float,
        top_p: float,
        tool_choice: str,
    ) -> AsyncGenerator[StreamChunk, None]:
        """降级为非流式"""
        response = await self.generate(
            messages, tools, max_tokens, temperature, top_p, tool_choice
        )
        if response.content:
            yield StreamChunk(type="content", content=response.content)
        for tc in response.tool_calls:
            yield StreamChunk(
                type="tool_call_end",
                tool_call_id=tc.id,
                tool_name=tc.name,
                tool_arguments_delta=tc.arguments,
            )
        yield StreamChunk(
            type="done",
            usage=response.usage,
            finish_reason=response.finish_reason,
        )
