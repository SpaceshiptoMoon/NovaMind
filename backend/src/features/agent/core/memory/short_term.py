"""
短期记忆管理器

从数据库加载对话消息，格式化为 OpenAI messages，
管理 Token 预算，超限时自动触发压缩策略。
"""
import json
from typing import Any, Dict, List

from novamind.features.agent.core.memory.interfaces import (
    IShortTermMemory,
    MemoryMessage,
    MemorySnapshot,
)
from novamind.features.agent.core.memory.token_budget import TokenBudget
from novamind.features.agent.core.memory.compress import ICompressionStrategy
from novamind.core.middleware.structured_logging import get_logger

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
        summary_repository: Any = None,  # ContextSummaryRepository
    ):
        self._msg_repo = message_repository
        self._tc_repo = tool_call_repository
        self._session_repo = session_repository
        self._token_budget = token_budget
        self._compression = compression_strategy
        self._summary_repo = summary_repository

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
        if self._summary_repo:
            try:
                latest_summary = await self._summary_repo.get_latest(conversation_id)
                if latest_summary:
                    summary_msg = MemoryMessage(
                        role="system",
                        content=latest_summary.summary_text,
                    )
                    summary_cutoff = latest_summary.created_at
            except Exception as e:
                logger.warning("摘要查询失败，加载全部消息", error=str(e))

        # 2. 从数据库加载消息
        if summary_cutoff:
            from sqlalchemy import select
            from novamind.features.agent.models.message import AgentMessage
            stmt = (
                select(AgentMessage)
                .where(
                    AgentMessage.conversation_id == conversation_id,
                    AgentMessage.created_at > summary_cutoff,
                )
                .order_by(AgentMessage.created_at.asc())
                .limit(200)
            )
            result = await self._session_repo.session.execute(stmt) if hasattr(self._session_repo, 'session') else None
            if result:
                db_messages = list(result.scalars().all())
            else:
                db_messages, _ = await self._msg_repo.list_by_conversation(
                    conversation_id, limit=200
                )
        else:
            db_messages, _ = await self._msg_repo.list_by_conversation(
                conversation_id, limit=200
            )

        db_tool_calls = await self._tc_repo.list_by_conversation(conversation_id)

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
        2. 还原 assistant 消息的 tool_calls（OpenAI 格式）
        3. 从 tool 消息中提取原始 call_id，按 tool_name 分组排队
        4. 确保 assistant.tool_calls[].id 与 tool.tool_call_id 一致
        """
        # message_id → [AgentToolCall]
        tool_calls_map: Dict[int, List[Any]] = {}
        for tc in db_tool_calls:
            tool_calls_map.setdefault(tc.message_id, []).append(tc)

        # tool_name → [tool_call_id] 队列，用于还原 assistant 消息的 call_id
        tool_call_ids_by_name: Dict[str, List[str]] = {}
        for msg in db_messages:
            if msg.role == "tool" and msg.tool_call_id:
                tool_call_ids_by_name.setdefault(msg.tool_name or "", []).append(
                    msg.tool_call_id
                )

        messages: List[MemoryMessage] = []
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
                    for tc in msg_tool_calls:
                        # 从同名 tool 消息队列中取出原始 call_id
                        name_queue = tool_call_ids_by_name.get(tc.tool_name, [])
                        call_id = name_queue.pop(0) if name_queue else f"call_{tc.id}"

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

        return messages

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
