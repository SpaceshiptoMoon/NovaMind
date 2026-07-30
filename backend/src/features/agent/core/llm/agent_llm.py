"""
Agent 专用 LLM 封装

组合持有 BaseLLM 实例（而非继承），提供 Agent 友好的接口：
- generate(): 非流式生成（委托给 BaseLLM）
- generate_stream(): 真正的流式输出（委托给 BaseLLM.generate_with_tools_stream + 降级策略）

选择组合而非继承的理由：
- BaseLLM 是 shared 层通用抽象，不应被 Agent 专用需求污染
- Agent 特有的流式工具调用逻辑封装在 feature 层

设计说明：本类只依赖 BaseLLM 抽象与 base_model.ToolStreamEvent，不对具体实现类
（如 OpenAICompatibleLLM）做 isinstance 判断，也不访问其私有属性
（_get_semaphore/client）。OpenAI 原生流式工具调用逻辑下沉为
BaseLLM.generate_with_tools_stream，由具体后端实现；不支持流式的后端会抛
NotImplementedError，本类降级为非流式。
"""
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from novamind_engine_core.ai_models.base_model import BaseLLM, ToolStreamEvent


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

        优先委托给 BaseLLM.generate_with_tools_stream（支持原生流式工具调用的后端，
        如 OpenAI 兼容）；后端不支持时抛 NotImplementedError，降级为非流式。
        """
        try:
            async for event in self._llm.generate_with_tools_stream(
                prompt=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                tool_choice=tool_choice,
            ):
                yield self._translate_stream_event(event)
        except NotImplementedError:
            async for chunk in self._stream_fallback(
                messages, tools, max_tokens, temperature, top_p, tool_choice
            ):
                yield chunk

    @staticmethod
    def _translate_stream_event(event: ToolStreamEvent) -> StreamChunk:
        """把 base_model.ToolStreamEvent 翻译为 Agent 自有的 StreamChunk。"""
        return StreamChunk(
            type=event.type,
            content=event.content,
            tool_call_id=event.tool_call_id,
            tool_name=event.tool_name,
            tool_arguments_delta=event.tool_arguments_delta,
            usage=event.usage,
            finish_reason=event.finish_reason,
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
