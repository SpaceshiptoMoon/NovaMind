"""
ReAct 循环引擎

实现 Agent 的 Think -> Act -> Observe -> Respond 循环。
支持流式（逐 token）和非流式（完整响应）两种模式。
内置 LLM 调用重试（jittered backoff）和单工具故障隔离。
"""
import asyncio
import json
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.ai_models.base_model import BaseLLM
from novamind.features.agent.core.tool.executor import ToolExecutor
from novamind.features.agent.core.tool.result import ToolResult, ToolResultStatus
from novamind.features.agent.core.retry import (
    RetryConfig, ContextOverflowError, retry_llm_call,
    _is_retryable_error, _is_context_overflow, _is_non_retryable,
)

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
        retry_config: Optional[RetryConfig] = None,
    ):
        self.tool_executor = tool_executor
        self._retry_config = retry_config or RetryConfig()

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
        stream: bool = True,
        compress_fn: Optional[Any] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """执行 Agent 对话循环，产出事件流

        Args:
            compress_fn: 可选的异步回调，签名 async (messages) -> new_messages。
                         上下文溢出时调用以压缩消息列表。
        """
        total_tokens = 0
        total_tool_calls = 0
        full_response = ""
        iteration = 0
        overflow_retry_used = False

        if not tools:
            async for event in self._generate_without_tools(
                llm_client, messages, max_tokens, temperature, top_p, enable_thinking, stream
            ):
                yield event
            return

        while iteration < max_iterations:
            iteration += 1
            meta: Dict[str, Any] = {}
            iteration_had_tools = False

            try:
                if stream:
                    async for event in self._run_iteration_stream(
                        llm_client, messages, tools, context,
                        max_tokens, temperature, top_p, enable_thinking,
                        meta=meta,
                    ):
                        yield event
                        if event.event_type == "content":
                            full_response += event.data.get("content", "")
                        elif event.event_type == "tool_call":
                            iteration_had_tools = True
                            total_tool_calls += 1
                else:
                    async for event in self._run_iteration_batch(
                        llm_client, messages, tools, context,
                        max_tokens, temperature, top_p, enable_thinking,
                        meta=meta,
                    ):
                        yield event
                        if event.event_type == "content":
                            full_response += event.data.get("content", "")
                        elif event.event_type == "tool_call":
                            iteration_had_tools = True
                            total_tool_calls += 1

                total_tokens += meta.get("total_tokens", 0)

                if not iteration_had_tools:
                    break

            except ContextOverflowError as e:
                logger.warning("上下文溢出", iteration=iteration, error=str(e))
                if compress_fn and not overflow_retry_used:
                    overflow_retry_used = True
                    try:
                        compressed = await compress_fn(messages)
                        if compressed and len(compressed) < len(messages):
                            messages.clear()
                            messages.extend(compressed)
                            iteration -= 1  # 不消耗迭代配额
                            logger.info(
                                "上下文自动压缩完成，重试迭代",
                                original=len(messages),
                                compressed=len(compressed),
                            )
                            continue
                    except Exception as comp_err:
                        logger.error("自动压缩失败", error=str(comp_err))
                yield AgentEvent("context_overflow", {"content": str(e)})
                break
            except Exception as e:
                logger.error("ReAct 循环异常", iteration=iteration, error=str(e))
                yield AgentEvent("error", {"content": f"Agent 执行出错：{str(e)}"})
                break

        truncated = iteration >= max_iterations

        # 最大迭代最终摘要：预算耗尽时，做一次无工具调用让模型总结进度
        if truncated and iteration_had_tools:
            try:
                summary_prompt = (
                    "你已达到最大迭代次数限制。请用 2-3 句话总结当前进度："
                    "已完成什么、还有什么未完成、下一步建议。"
                    "不要使用任何工具。"
                )
                messages.append({"role": "user", "content": summary_prompt})
                async for event in self._generate_without_tools_stream(
                    llm_client, messages, max_tokens=1024,
                    temperature=0.5, top_p=0.8,
                ):
                    if event.event_type == "content":
                        full_response += event.data.get("content", "")
                        yield event
                    elif event.event_type == "done":
                        total_tokens += event.data.get("total_tokens", 0)
            except Exception as e:
                logger.warning("最大迭代最终摘要生成失败", error=str(e))

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

    # ==================== 流式重试辅助 ====================

    async def _retry_generate_stream(
        self,
        agent_llm: Any,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> AsyncGenerator[Any, None]:
        """带重试的流式生成：在首个 chunk 到达前重试瞬时错误"""
        from novamind.features.agent.core.llm.agent_llm import AgentLLM

        cfg = self._retry_config
        attempt = 0

        while True:
            attempt += 1
            stream = agent_llm.generate_stream(
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )
            first_chunk_received = False
            try:
                async for chunk in stream:
                    first_chunk_received = True
                    yield chunk
                return  # 流正常结束
            except Exception as exc:
                if first_chunk_received:
                    raise  # 流已开始，不重试

                if _is_context_overflow(exc):
                    raise ContextOverflowError(str(exc)) from exc
                if _is_non_retryable(exc):
                    raise
                if not _is_retryable_error(exc):
                    raise
                if attempt >= cfg.max_retries:
                    raise

                import random
                delay = min(cfg.base_delay * (2 ** (attempt - 1)), cfg.max_delay)
                jitter = random.uniform(0, cfg.jitter_max)
                logger.warning(
                    "流式 LLM 调用失败，准备重试",
                    attempt=attempt,
                    max_retries=cfg.max_retries,
                    delay=f"{delay + jitter:.1f}s",
                    error=str(exc)[:200],
                )
                await asyncio.sleep(delay + jitter)

    # ==================== 流式迭代 ====================

    async def _run_iteration_stream(
        self,
        llm_client: BaseLLM,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        context: Dict[str, Any],
        max_tokens: int,
        temperature: float,
        top_p: float,
        enable_thinking: bool,
        meta: Dict[str, Any],
    ) -> AsyncGenerator[AgentEvent, None]:
        """流式迭代：逐 token 产出事件，不缓存（含重试）"""
        from novamind.features.agent.core.llm.agent_llm import AgentLLM, CollectedToolCall

        agent_llm = AgentLLM(llm_client)
        content_parts: List[str] = []
        collected: Dict[str, CollectedToolCall] = {}
        total_tokens = 0

        async for chunk in self._retry_generate_stream(
            agent_llm, messages, tools,
            max_tokens, temperature, top_p,
        ):
            if chunk.type == "content":
                content_parts.append(chunk.content)
                yield AgentEvent("content", {"content": chunk.content})

            elif chunk.type == "reasoning":
                yield AgentEvent("reasoning", {"content": chunk.content})

            elif chunk.type == "tool_call_end":
                collected[chunk.tool_call_id] = CollectedToolCall(
                    id=chunk.tool_call_id,
                    name=chunk.tool_name or "",
                    arguments=chunk.tool_arguments_delta,
                )

            elif chunk.type == "done":
                if chunk.usage:
                    total_tokens = chunk.usage.get("total_tokens", 0)

        meta["total_tokens"] = total_tokens

        if not collected:
            return

        # 有工具调用 → 执行并产出事件
        tool_events, assistant_msg, tool_result_msgs = (
            await self._process_tool_calls_collected(collected, context)
        )
        for event in tool_events:
            yield event

        messages.append(assistant_msg)
        for msg in tool_result_msgs:
            messages.append(msg)

    # ==================== 非流式迭代 ====================

    async def _run_iteration_batch(
        self,
        llm_client: BaseLLM,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        context: Dict[str, Any],
        max_tokens: int,
        temperature: float,
        top_p: float,
        enable_thinking: bool,
        meta: Dict[str, Any],
    ) -> AsyncGenerator[AgentEvent, None]:
        """非流式迭代：使用 generate_with_tools() 等待完整响应"""
        total_tokens = 0

        response = await retry_llm_call(
            lambda: llm_client.generate_with_tools(
                prompt=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                tool_choice="auto",
                enable_thinking=enable_thinking,
            ),
            config=self._retry_config,
        )

        if response.usage:
            total_tokens = response.usage.get("total_tokens", 0)

        if response.reasoning:
            yield AgentEvent("reasoning", {"content": response.reasoning})

        if response.tool_calls:
            if response.content:
                yield AgentEvent("content", {"content": response.content})

            tool_events, assistant_msg, tool_result_msgs = (
                await self._process_tool_calls(response.tool_calls, context)
            )
            for event in tool_events:
                yield event

            messages.append(assistant_msg)
            for msg in tool_result_msgs:
                messages.append(msg)

            meta["total_tokens"] = total_tokens
            return

        if response.content:
            yield AgentEvent("content", {"content": response.content})

        meta["total_tokens"] = total_tokens

    # ==================== 无工具路径 ====================

    async def _generate_without_tools(
        self,
        llm_client: BaseLLM,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        top_p: float,
        enable_thinking: bool,
        stream: bool,
    ) -> AsyncGenerator[AgentEvent, None]:
        """无工具时的纯文本生成"""
        try:
            if stream:
                async for event in self._generate_without_tools_stream(
                    llm_client, messages, max_tokens, temperature, top_p
                ):
                    yield event
            else:
                async for event in self._generate_without_tools_batch(
                    llm_client, messages, max_tokens, temperature, top_p, enable_thinking
                ):
                    yield event
        except Exception as e:
            yield AgentEvent("error", {"content": f"生成失败：{str(e)}"})

    async def _generate_without_tools_stream(
        self,
        llm_client: BaseLLM,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> AsyncGenerator[AgentEvent, None]:
        """无工具流式生成（含重试）"""
        from novamind.features.agent.core.llm.agent_llm import AgentLLM

        agent_llm = AgentLLM(llm_client)
        full_response = ""
        total_tokens = 0

        async for chunk in self._retry_generate_stream(
            agent_llm, messages, None,
            max_tokens, temperature, top_p,
        ):
            if chunk.type == "content":
                full_response += chunk.content
                yield AgentEvent("content", {"content": chunk.content})
            elif chunk.type == "done":
                if chunk.usage:
                    total_tokens = chunk.usage.get("total_tokens", 0)

        yield AgentEvent(
            "done",
            {
                "full_response": full_response,
                "tool_calls_count": 0,
                "total_tokens": total_tokens,
                "iterations": 1,
            },
        )

    async def _generate_without_tools_batch(
        self,
        llm_client: BaseLLM,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        top_p: float,
        enable_thinking: bool,
    ) -> AsyncGenerator[AgentEvent, None]:
        """无工具非流式生成"""
        response = await retry_llm_call(
            lambda: llm_client.generate_with_tools(
                prompt=messages,
                tools=None,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                enable_thinking=enable_thinking,
            ),
            config=self._retry_config,
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

    # ==================== 工具调用处理 ====================

    async def _execute_single_tool(
        self,
        tool_name: str,
        raw_arguments: Any,
        call_id: str,
        context: Dict[str, Any],
    ) -> Tuple[AgentEvent, AgentEvent, Dict[str, Any], Dict[str, Any]]:
        """执行单个工具调用（含 JSON 解析守卫 + 异常隔离）

        Returns: (tool_call_event, tool_result_event, assistant_tc_dict, tool_result_msg)
        """
        # JSON 解析守卫
        try:
            args = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else raw_arguments
            )
        except json.JSONDecodeError:
            args = {}
            logger.warning("工具参数 JSON 解析失败", tool_name=tool_name, raw=repr(raw_arguments)[:200])

        call_event = AgentEvent("tool_call", {
            "tool_name": tool_name, "arguments": args, "call_id": call_id,
        })

        # 单工具异常隔离
        try:
            result = await self.tool_executor.execute(
                tool_name=tool_name, arguments=args, context=context,
            )
        except Exception as e:
            logger.error("工具执行异常，隔离跳过", tool_name=tool_name, error=str(e))
            result = ToolResult(
                status=ToolResultStatus.ERROR,
                content=str(e),
                error_message=str(e),
            )

        # SSE 前端用预览，DB 用完整结果
        oversized = result.metadata.get("_oversized", False)
        if oversized:
            sse_content = result.metadata.get("_preview", result.content[:1500])
        else:
            sse_content = result.content

        result_event = AgentEvent("tool_result", {
            "tool_name": tool_name,
            "result": sse_content,
            "full_result": result.content,
            "duration_ms": result.duration_ms,
            "status": (
                "timeout" if result.status == ToolResultStatus.TIMEOUT
                else "completed" if result.status == ToolResultStatus.SUCCESS
                else "failed"
            ),
            "call_id": call_id,
            "oversized": oversized,
            "original_length": result.metadata.get("_original_length", len(result.content)),
        })

        tc_dict = {
            "id": call_id, "type": "function",
            "function": {
                "name": tool_name,
                "arguments": raw_arguments if isinstance(raw_arguments, str) else json.dumps(raw_arguments),
            },
        }

        tool_msg = {"role": "tool", "tool_call_id": call_id, "content": result.content}

        return call_event, result_event, tc_dict, tool_msg

    async def _process_tool_calls(
        self,
        tool_calls: List[Any],
        context: Dict[str, Any],
    ) -> Tuple[List[AgentEvent], Dict[str, Any], List[Dict[str, Any]]]:
        """处理非流式路径的工具调用（并行执行，单工具故障隔离）"""
        import uuid

        items = []
        for tc in tool_calls:
            call_id = tc.id or f"call_{uuid.uuid4().hex[:8]}"
            items.append((call_id, tc.name, tc.arguments))

        if len(items) == 1:
            call_evt, result_evt, tc_dict, tool_msg = await self._execute_single_tool(
                items[0][1], items[0][2], items[0][0], context,
            )
            events = [call_evt, result_evt]
            assistant_tool_calls = [tc_dict]
            tool_result_messages = [tool_msg]
        else:
            coros = [
                self._execute_single_tool(name, args, cid, context)
                for cid, name, args in items
            ]
            results = await asyncio.gather(*coros)
            events = []
            assistant_tool_calls = []
            tool_result_messages = []
            for call_evt, result_evt, tc_dict, tool_msg in results:
                events.append(call_evt)
                events.append(result_evt)
                assistant_tool_calls.append(tc_dict)
                tool_result_messages.append(tool_msg)

        self._apply_turn_budget(tool_result_messages, context.get("tool_result_turn_budget", 100_000))

        assistant_msg = {"role": "assistant", "content": None, "tool_calls": assistant_tool_calls}
        return events, assistant_msg, tool_result_messages

    async def _process_tool_calls_collected(
        self,
        collected: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Tuple[List[AgentEvent], Dict[str, Any], List[Dict[str, Any]]]:
        """处理流式路径收集到的工具调用（并行执行，单工具故障隔离）"""
        items = [(cid, tc.name, tc.arguments) for cid, tc in collected.items()]

        if len(items) == 1:
            call_evt, result_evt, tc_dict, tool_msg = await self._execute_single_tool(
                items[0][1], items[0][2], items[0][0], context,
            )
            events = [call_evt, result_evt]
            assistant_tool_calls = [tc_dict]
            tool_result_messages = [tool_msg]
        else:
            coros = [
                self._execute_single_tool(name, args, cid, context)
                for cid, name, args in items
            ]
            results = await asyncio.gather(*coros)
            events = []
            assistant_tool_calls = []
            tool_result_messages = []
            for call_evt, result_evt, tc_dict, tool_msg in results:
                events.append(call_evt)
                events.append(result_evt)
                assistant_tool_calls.append(tc_dict)
                tool_result_messages.append(tool_msg)

        self._apply_turn_budget(tool_result_messages, context.get("tool_result_turn_budget", 100_000))

        assistant_msg = {"role": "assistant", "content": None, "tool_calls": assistant_tool_calls}
        return events, assistant_msg, tool_result_messages

    @staticmethod
    def _apply_turn_budget(
        tool_result_messages: List[Dict[str, Any]],
        budget: int = 100_000,
    ) -> None:
        """Layer 3: 单轮工具结果总量超出预算时，裁剪最大结果的内存上下文"""
        total = sum(len(msg.get("content", "")) for msg in tool_result_messages)
        if total <= budget:
            return

        for msg in sorted(
            tool_result_messages,
            key=lambda m: len(m.get("content", "")),
            reverse=True,
        ):
            if total <= budget:
                break
            content = msg.get("content", "")
            if len(content) > 1500:
                excess = len(content) - 1500
                msg["content"] = content[:1500] + "\n...[单轮结果总预算限制已截断]"
                total -= excess
