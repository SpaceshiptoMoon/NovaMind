"""
ReAct 循环引擎

实现 Agent 的 Think -> Act -> Observe -> Respond 循环。
"""
import json
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from src.core.middleware.structured_logging import get_logger
from src.shared.ai_models.base_model import BaseLLM
from src.features.agent.core.executor import ToolExecutor

logger = get_logger(__name__)


@dataclass
class AgentEvent:
    """Agent 事件"""
    event_type: str
    data: Dict[str, Any]


class AgentEngine:
    """Agent 执行引擎"""

    def __init__(
        self,
        tool_executor: ToolExecutor,
    ):
        self.tool_executor = tool_executor

    async def run(
        self,
        llm_client: BaseLLM,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        context: Dict[str, Any],
        max_iterations: int = 10,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.8,
        enable_thinking: bool = False,
    ) -> AsyncGenerator[AgentEvent, None]:
        """执行 Agent 对话循环，产出事件流"""
        total_tokens = 0
        total_tool_calls = 0
        full_response = ""
        iteration = 0

        if not tools:
            async for event in self._generate_without_tools(
                llm_client, messages, max_tokens, temperature, top_p, enable_thinking
            ):
                yield event
            return

        while iteration < max_iterations:
            iteration += 1

            try:
                response = await llm_client.generate_with_tools(
                    prompt=messages,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    tool_choice="auto",
                    enable_thinking=enable_thinking,
                )

                if response.usage:
                    total_tokens += response.usage.get("total_tokens", 0)

                # LLM 返回思考过程（thinking 模式）
                if response.reasoning:
                    yield AgentEvent("reasoning", {"content": response.reasoning})

                # LLM 返回工具调用
                if response.tool_calls:
                    if response.content:
                        full_response += response.content
                        yield AgentEvent("content", {"content": response.content})

                    # 处理工具调用，获取事件和消息
                    events, assistant_msg, tool_result_msgs = (
                        await self._process_tool_calls(response.tool_calls, context)
                    )
                    total_tool_calls += len(response.tool_calls)

                    # 发送工具相关事件
                    for event in events:
                        yield event

                    messages.append(assistant_msg)
                    for msg in tool_result_msgs:
                        messages.append(msg)
                    continue

                # LLM 返回纯文本（最终回答）
                if response.content:
                    full_response += response.content
                    yield AgentEvent("content", {"content": response.content})

                break

            except Exception as e:
                logger.error("ReAct 循环异常", iteration=iteration, error=str(e))
                yield AgentEvent("error", {"content": f"Agent 执行出错：{str(e)}"})
                break

        truncated = iteration >= max_iterations
        yield AgentEvent(
            "done",
            {
                "full_response": full_response,
                "tool_calls_count": total_tool_calls,
                "total_tokens": total_tokens,
                "iterations": iteration,
                "truncated": truncated,
            },
        )

    async def _process_tool_calls(
        self,
        tool_calls: List[Any],
        context: Dict[str, Any],
    ) -> Tuple[List[AgentEvent], Dict[str, Any], List[Dict[str, Any]]]:
        """
        处理工具调用

        Returns:
            (events, assistant_msg, tool_result_messages)
        """
        import uuid

        events: List[AgentEvent] = []
        assistant_tool_calls = []
        tool_result_messages = []

        for tc in tool_calls:
            call_id = tc.id or f"call_{uuid.uuid4().hex[:8]}"

            # 解析参数
            args = (
                json.loads(tc.arguments)
                if isinstance(tc.arguments, str)
                else tc.arguments
            )

            # tool_call 事件
            events.append(
                AgentEvent(
                    "tool_call",
                    {
                        "tool_name": tc.name,
                        "arguments": args,
                        "call_id": call_id,
                    },
                )
            )

            # 执行工具
            try:
                result_text, duration_ms = await self.tool_executor.execute(
                    tool_name=tc.name,
                    arguments=args,
                    context=context,
                )
                status = "completed"
            except Exception as e:
                result_text = f"工具执行失败：{str(e)}"
                duration_ms = 0
                status = "failed"

            # tool_result 事件
            events.append(
                AgentEvent(
                    "tool_result",
                    {
                        "tool_name": tc.name,
                        "result": result_text[:2000],
                        "duration_ms": duration_ms,
                        "status": status,
                        "call_id": call_id,
                    },
                )
            )

            # 构建消息
            assistant_tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments),
                    },
                }
            )

            tool_result_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result_text,
                }
            )

        assistant_msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": assistant_tool_calls,
        }

        return events, assistant_msg, tool_result_messages

    async def _generate_without_tools(
        self,
        llm_client: BaseLLM,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        top_p: float,
        enable_thinking: bool = False,
    ) -> AsyncGenerator[AgentEvent, None]:
        """无工具时的纯文本生成"""
        try:
            response = await llm_client.generate_with_tools(
                prompt=messages,
                tools=None,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                enable_thinking=enable_thinking,
            )

            if response.reasoning:
                yield AgentEvent("reasoning", {"content": response.reasoning})

            if response.content:
                yield AgentEvent("content", {"content": response.content})

            total_tokens = response.usage.get("total_tokens", 0) if response.usage else 0

            yield AgentEvent(
                "done",
                {
                    "full_response": response.content or "",
                    "tool_calls_count": 0,
                    "total_tokens": total_tokens,
                    "iterations": 1,
                },
            )

        except Exception as e:
            yield AgentEvent("error", {"content": f"生成失败：{str(e)}"})
