"""
短期记忆管理器

从数据库加载对话消息，格式化为 OpenAI messages，
管理 Token 预算，超限时自动触发压缩策略。
"""
import json
from typing import Any, Dict, List

from novamind.engines.agent.memory.interfaces import (
    IShortTermMemory,
    MemoryMessage,
    MemorySnapshot,
)
from novamind.engines.agent.memory.token_budget import TokenBudget
from novamind.engines.agent.memory.compress import ICompressionStrategy
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class ShortTermMemory(IShortTermMemory):
    """
    短期记忆管理器

    核心流程：
    1. 从 agent_context_summaries 查询最新摘要
    2. 从数据库加载摘要之后的消息和工具调用记录
    3. 转换为统一的 MemoryMessage 列表
    4. 计算 token 数，超预算时触发压缩
    5. 组装 MemorySnapshot 输出给 AgentEngine
    """

    def __init__(
        self,
        message_repository: Any,  # MessageRepository
        tool_call_repository: Any,  # ToolCallRepository
        session_repository: Any,  # SessionRepository
        token_budget: TokenBudget,
        compression_strategy: ICompressionStrategy,
        summary_store: Any = None,  # ContextSummaryStorePort
    ):
        self._msg_repo = message_repository
        self._tc_repo = tool_call_repository
        self._session_repo = session_repository
        self._token_budget = token_budget
        self._compression = compression_strategy
        self._summary_store = summary_store

    async def build_context(
        self,
        system_prompt: str,
        conversation_id: int,
        max_tokens: int,
        reserve_tokens: int = 1024,
    ) -> MemorySnapshot:
        """
        构建上下文快照

        Args:
            max_tokens: 模型上下文窗口大小（由 agent.context_window 决定，非生成上限）
            reserve_tokens: 为 LLM 生成预留的 token 数

        步骤：
        1. 加载 DB 消息 + 工具调用记录
        2. 转换为 MemoryMessage 列表
        3. 计算 token 数
        4. 超出预算 → 压缩策略
        5. 组装 OpenAI 格式 messages
        """
        # 1. 查询最新摘要
        summary_msg = None
        summary_cutoff = None
        if self._summary_store:
            try:
                latest_summary = await self._summary_store.get_latest_summary(conversation_id)
                if latest_summary:
                    summary_msg = MemoryMessage(
                        role="system",
                        content=latest_summary.summary_text,
                    )
                    summary_cutoff = latest_summary.created_at
            except Exception as e:
                logger.warning("摘要查询失败，加载全部消息", error=str(e))

        # 2. 从数据库加载消息（命中摘要 → 增量加载 cutoff 之后；否则全部）
        if summary_cutoff:
            db_messages, _ = await self._msg_repo.list_by_conversation_after(
                conversation_id, after=summary_cutoff, limit=200
            )
        else:
            db_messages, _ = await self._msg_repo.list_by_conversation(
                conversation_id, limit=200
            )

        # 工具调用记录：命中摘要时仅加载 cutoff 之后的，避免 cutoff 前 assistant 消息
        # 已被摘要替代而 tool_calls 成孤儿（浪费 + 潜在错配）
        db_tool_calls = await self._tc_repo.list_by_conversation(
            conversation_id, after=summary_cutoff
        )

        # 2. 转换为内部消息模型
        memory_messages = self._convert_db_messages(db_messages, db_tool_calls)

        # 3. 如果有摘要，前置到消息列表
        if summary_msg:
            memory_messages = [summary_msg] + memory_messages

        # 3. 计算 token 预算
        available_tokens = max_tokens - reserve_tokens
        system_tokens = self._token_budget.count_text_tokens(system_prompt)
        messages_tokens = self._token_budget.count_messages_tokens(memory_messages)
        total_tokens = system_tokens + messages_tokens

        compressed = False
        compression_ratio = 1.0

        # 4. 超出预算，触发压缩
        if total_tokens > available_tokens:
            memory_messages, compressed, compression_ratio = (
                await self._compression.compress(
                    messages=memory_messages,
                    available_tokens=available_tokens - system_tokens,
                    token_budget=self._token_budget,
                    conversation_id=conversation_id,
                )
            )
            messages_tokens = self._token_budget.count_messages_tokens(
                memory_messages
            )
            total_tokens = system_tokens + messages_tokens
            logger.info(
                "上下文已压缩",
                conversation_id=conversation_id,
                compression_ratio=compression_ratio,
                tokens_after=total_tokens,
            )

        # 5. 组装 OpenAI 格式消息
        openai_messages = self._build_openai_messages(
            system_prompt, memory_messages
        )

        return MemorySnapshot(
            messages=openai_messages,
            total_tokens=total_tokens,
            compressed=compressed,
            compression_ratio=compression_ratio,
        )

    async def add_message(
        self, conversation_id: int, message: MemoryMessage
    ) -> None:
        """添加一条消息到短期记忆（写入数据库）"""
        await self._msg_repo.create(
            conversation_id=conversation_id,
            role=message.role,
            content=message.content,
            tool_call_id=message.tool_call_id,
            tool_name=message.tool_name,
            token_count=message.token_count,
            extra=message.metadata,
        )

    async def get_token_count(self, conversation_id: int) -> int:
        """获取当前对话的 token 估计值"""
        db_messages, _ = await self._msg_repo.list_by_conversation(
            conversation_id, limit=200
        )
        db_tool_calls = await self._tc_repo.list_by_conversation(conversation_id)
        memory_messages = self._convert_db_messages(db_messages, db_tool_calls)
        return self._token_budget.count_messages_tokens(memory_messages)

    def _convert_db_messages(
        self, db_messages: List[Any], db_tool_calls: List[Any]
    ) -> List[MemoryMessage]:
        """
        将数据库消息记录转换为 MemoryMessage 列表

        核心逻辑：
        1. 构建 message_id → [AgentToolCall] 映射
        2. 还原 assistant 消息的 tool_calls（OpenAI 格式），call_id 直接取
           AgentToolCall.call_id —— 新链路落库时 call_id 已与 tool 消息
           tool_call_id 一致（同源于 agent_engine 的 _execute_single_tool.call_id）；
           历史数据 call_id 为 null 时 fallback 到 f"call_{tc.id}"
        3. load-time 配对断言（_assert_tool_call_pairing）：assistant.tool_calls[].id
           集合应与紧随其后的 tool 消息 tool_call_id 集合一致；新链路不一致 raise，
           历史链路（用了 fallback）降级 warning 不中断
        """
        # message_id → [AgentToolCall]
        tool_calls_map: Dict[int, List[Any]] = {}
        for tc in db_tool_calls:
            tool_calls_map.setdefault(tc.message_id, []).append(tc)

        messages: List[MemoryMessage] = []
        # 记录每条带 tool_calls 的 assistant 在 messages 中的索引 + 是否用了 fallback，
        # 供 _assert_tool_call_pairing 判定新链路（严格 raise）还是历史链路（降级 warning）
        assistant_tc_meta: List[tuple] = []
        for msg in db_messages:
            if msg.role == "user":
                messages.append(
                    MemoryMessage(
                        role="user",
                        content=msg.content or "",
                        token_count=msg.token_count,
                    )
                )

            elif msg.role == "assistant":
                msg_tool_calls = tool_calls_map.get(msg.id, [])
                if msg_tool_calls:
                    openai_tool_calls = []
                    used_fallback = False
                    for tc in msg_tool_calls:
                        # 直接用 AgentToolCall.call_id（新链路已与 tool 消息 tool_call_id 一致）；
                        # 历史数据 call_id 为 null 时 fallback 到 f"call_{tc.id}"
                        if tc.call_id:
                            call_id = tc.call_id
                        else:
                            call_id = f"call_{tc.id}"
                            used_fallback = True

                        openai_tool_calls.append(
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": tc.tool_name,
                                    "arguments": (
                                        tc.arguments
                                        if isinstance(tc.arguments, str)
                                        else json.dumps(
                                            tc.arguments, ensure_ascii=False
                                        )
                                    ),
                                },
                            }
                        )
                    messages.append(
                        MemoryMessage(
                            role="assistant",
                            content=msg.content,
                            tool_calls=openai_tool_calls,
                            token_count=msg.token_count,
                        )
                    )
                    assistant_tc_meta.append((len(messages) - 1, used_fallback))
                else:
                    messages.append(
                        MemoryMessage(
                            role="assistant",
                            content=msg.content or "",
                            token_count=msg.token_count,
                        )
                    )

            elif msg.role == "tool":
                messages.append(
                    MemoryMessage(
                        role="tool",
                        content=msg.content or "",
                        tool_call_id=msg.tool_call_id,
                        tool_name=msg.tool_name,
                        token_count=msg.token_count,
                    )
                )

        self._assert_tool_call_pairing(messages, assistant_tc_meta)
        return messages

    def _assert_tool_call_pairing(
        self,
        messages: List[MemoryMessage],
        assistant_tc_meta: List[tuple],
    ) -> None:
        """load-time 配对断言：每条带 tool_calls 的 assistant，其 tool_calls[].id 集合应与
        紧随其后的 tool 消息 tool_call_id 集合一致。

        - 新链路（未用 fallback，tc.call_id 非空）不一致 → raise ValueError，早失败早暴露
        - 历史链路（用了 fallback，tc.call_id 为 null）→ 降级 warning，不中断
        """
        n = len(messages)
        for idx, used_fallback in assistant_tc_meta:
            assistant_ids = [tc["id"] for tc in messages[idx].tool_calls]
            # 收集紧随其后的 tool 消息 tool_call_id
            tool_ids: List[str] = []
            j = idx + 1
            while j < n and messages[j].role == "tool":
                if messages[j].tool_call_id:
                    tool_ids.append(messages[j].tool_call_id)
                j += 1

            if used_fallback:
                # 历史链路：call_id 为 null，无法严格配对，降级 warning
                logger.warning(
                    "assistant 决策消息 tool_calls 用了 fallback call_id（历史数据），"
                    "跳过配对断言",
                    assistant_ids=assistant_ids,
                    tool_ids=tool_ids,
                )
                continue

            # 新链路：严格断言 assistant.tool_calls id 与 tool 消息 tool_call_id 配对
            if set(assistant_ids) != set(tool_ids):
                raise ValueError(
                    f"assistant.tool_calls id 与 tool 消息 tool_call_id 不配对"
                    f"（新链路应一致）: assistant={assistant_ids} vs tool={tool_ids}"
                )

    def _build_openai_messages(
        self, system_prompt: str, memory_messages: List[MemoryMessage]
    ) -> List[Dict[str, Any]]:
        """
        将 MemoryMessage 列表组装为 OpenAI API 格式

        TODO: 完善工具调用消息的还原逻辑
        """
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        for msg in memory_messages:
            if msg.role == "user":
                messages.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                if msg.tool_calls:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": msg.content,
                            "tool_calls": msg.tool_calls,
                        }
                    )
                else:
                    messages.append(
                        {"role": "assistant", "content": msg.content}
                    )
            elif msg.role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id or "",
                        "content": msg.content,
                    }
                )
        return messages
