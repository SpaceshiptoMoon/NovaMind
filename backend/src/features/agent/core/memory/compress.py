"""
压缩策略

当对话 token 数超出预算时，通过压缩策略裁剪上下文。
提供两种实现：
- SlidingWindowCompression: 保留最近 N 条 + 摘要替换早期消息
- PriorityBasedCompression: 按优先级裁剪（工具结果 < 旧对话 < 新对话）
"""
from abc import ABC, abstractmethod
from typing import Any, Callable, List, Optional, Tuple

from src.features.agent.core.memory.interfaces import MemoryMessage
from src.features.agent.core.memory.token_budget import TokenBudget
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class ICompressionStrategy(ABC):
    """压缩策略接口"""

    @abstractmethod
    async def compress(
        self,
        messages: List[MemoryMessage],
        available_tokens: int,
        token_budget: TokenBudget,
    ) -> Tuple[List[MemoryMessage], bool, float]:
        """
        压缩消息列表以适应 token 预算

        Args:
            messages: 原始消息列表
            available_tokens: 可用 token 预算
            token_budget: Token 计数器

        Returns:
            (压缩后消息列表, 是否发生压缩, 压缩比率)
        """
        ...


class SlidingWindowCompression(ICompressionStrategy):
    """
    滑动窗口压缩

    策略：
    1. 保留最近 keep_recent_count 条消息不动
    2. 对窗口外的早期消息，调用 LLM 生成摘要
    3. 摘要作为一条 system 消息注入到消息列表头部
    4. 如果仍超预算，截断摘要长度
    """

    def __init__(
        self,
        llm_client_factory: Callable,
        keep_recent_count: int = 6,
        max_summary_tokens: int = 500,
    ):
        self._llm_factory = llm_client_factory
        self._keep_recent = keep_recent_count
        self._max_summary_tokens = max_summary_tokens

    async def compress(
        self,
        messages: List[MemoryMessage],
        available_tokens: int,
        token_budget: TokenBudget,
    ) -> Tuple[List[MemoryMessage], bool, float]:
        if len(messages) <= self._keep_recent:
            return messages, False, 1.0

        # 1. 分割
        early_messages = messages[: -self._keep_recent]
        recent_messages = messages[-self._keep_recent :]

        # 2. 生成摘要
        summary = await self._generate_summary(early_messages)

        # 3. 构建摘要消息
        summary_msg = MemoryMessage(
            role="system",
            content=f"[之前对话的摘要]\n{summary}",
        )

        # 4. 组合：摘要 + 最近消息
        compressed = [summary_msg] + recent_messages

        # 5. 验证 token 数
        current_tokens = token_budget.count_messages_tokens(compressed)
        original_tokens = token_budget.count_messages_tokens(messages)

        # 如果仍超预算，逐步移除摘要后的最早消息
        while current_tokens > available_tokens and len(compressed) > 2:
            removed = compressed.pop(1)  # 移除摘要后的第一条
            current_tokens = token_budget.count_messages_tokens(compressed)
            logger.debug(
                "滑动窗口移除消息",
                removed_role=removed.role,
                remaining=len(compressed),
            )

        compression_ratio = current_tokens / original_tokens if original_tokens > 0 else 1.0
        logger.info(
            "滑动窗口压缩完成",
            original_count=len(messages),
            compressed_count=len(compressed),
            ratio=round(compression_ratio, 2),
        )
        return compressed, True, compression_ratio

    async def _generate_summary(self, messages: List[MemoryMessage]) -> str:
        """调用 LLM 生成早期消息摘要"""
        conversation_text = ""
        for msg in messages:
            if msg.content:
                conversation_text += f"[{msg.role}]: {msg.content}\n"

        if not conversation_text.strip():
            return ""

        prompt = (
            "请用简洁的中文总结以下对话的关键信息，"
            "包括用户意图、讨论的结论和重要细节。"
            "不要包含寒暄和无关内容。\n\n"
            f"对话内容：\n{conversation_text}"
        )

        try:
            llm = self._llm_factory()
            summary = await llm.generate_text(
                prompt=prompt,
                max_tokens=self._max_summary_tokens,
                temperature=0.3,
            )
            return summary.strip()
        except Exception as e:
            logger.warning("摘要生成失败，回退到截断模式", error=str(e))
            # 回退：直接截断早期消息
            return self._truncate_messages(messages)

    @staticmethod
    def _truncate_messages(messages: List[MemoryMessage]) -> str:
        """截断拼接作为简单摘要回退"""
        parts = []
        for msg in messages:
            if msg.content:
                text = msg.content[:200]
                if len(msg.content) > 200:
                    text += "..."
                parts.append(f"[{msg.role}]: {text}")
        return "\n".join(parts)


class PriorityBasedCompression(ICompressionStrategy):
    """
    优先级压缩

    消息优先级（从低到高，低优先级优先裁剪）：
    1. 旧工具调用及其结果（tool 角色）
    2. 旧的普通对话消息（按位置从远到近）
    3. 最近的对话消息
    4. 系统提示词（不可裁剪）

    裁剪动作：
    - 工具结果：截断内容到 max_result_chars
    - 仍超预算：直接移除最旧的消息对（tool + 对应 assistant）
    """

    def __init__(self, max_result_chars: int = 2000):
        self._max_result_chars = max_result_chars

    async def compress(
        self,
        messages: List[MemoryMessage],
        available_tokens: int,
        token_budget: TokenBudget,
    ) -> Tuple[List[MemoryMessage], bool, float]:
        original_tokens = token_budget.count_messages_tokens(messages)
        if original_tokens <= available_tokens:
            return messages, False, 1.0

        working = list(messages)

        # 阶段一：截断工具结果
        working = self._truncate_tool_results(working)
        current_tokens = token_budget.count_messages_tokens(working)
        if current_tokens <= available_tokens:
            ratio = current_tokens / original_tokens if original_tokens > 0 else 1.0
            return working, True, ratio

        # 阶段二：从最旧开始移除完整的工具调用组
        working = self._remove_oldest_tool_groups(working, available_tokens, token_budget)
        current_tokens = token_budget.count_messages_tokens(working)
        if current_tokens <= available_tokens:
            ratio = current_tokens / original_tokens if original_tokens > 0 else 1.0
            return working, True, ratio

        # 阶段三：从最旧开始移除普通消息（成对移除 user+assistant）
        working = self._remove_oldest_pairs(working, available_tokens, token_budget)
        current_tokens = token_budget.count_messages_tokens(working)

        ratio = current_tokens / original_tokens if original_tokens > 0 else 1.0
        logger.info(
            "优先级压缩完成",
            original_count=len(messages),
            compressed_count=len(working),
            ratio=round(ratio, 2),
        )
        return working, True, ratio

    def _truncate_tool_results(
        self, messages: List[MemoryMessage]
    ) -> List[MemoryMessage]:
        """截断工具结果内容"""
        result = []
        for msg in messages:
            if msg.role == "tool" and len(msg.content) > self._max_result_chars:
                truncated = MemoryMessage(
                    role=msg.role,
                    content=msg.content[: self._max_result_chars] + "\n...[已截断]",
                    tool_call_id=msg.tool_call_id,
                    tool_name=msg.tool_name,
                    token_count=msg.token_count,
                    metadata={**msg.metadata, "truncated": True},
                )
                result.append(truncated)
            else:
                result.append(msg)
        return result

    def _remove_oldest_tool_groups(
        self,
        messages: List[MemoryMessage],
        available_tokens: int,
        token_budget: TokenBudget,
    ) -> List[MemoryMessage]:
        """
        从最旧开始移除完整的工具调用组（assistant + 所有关联 tool 消息）

        一个工具调用组的结构：
          assistant(含 tool_calls) + 紧随其后所有 tool_call_id 匹配的 tool 消息

        必须整组删除，否则残留的 assistant tool_calls 引用缺失的 tool 响应，
        导致 OpenAI API 报错。
        """
        working = list(messages)

        while True:
            current_tokens = token_budget.count_messages_tokens(working)
            if current_tokens <= available_tokens:
                break

            # 找到第一个含 tool_calls 的 assistant 消息
            group_start = None
            call_ids: set = set()
            for i, msg in enumerate(working):
                if msg.role == "assistant" and msg.tool_calls:
                    group_start = i
                    call_ids = {
                        tc.get("id")
                        for tc in msg.tool_calls
                        if tc.get("id")
                    }
                    break

            if group_start is None:
                break  # 没有更多工具调用组可移除

            # 找到该 assistant 后续所有匹配的 tool 消息
            group_end = group_start + 1
            while group_end < len(working):
                msg = working[group_end]
                if msg.role == "tool" and msg.tool_call_id in call_ids:
                    group_end += 1
                else:
                    break

            # 整组删除
            logger.debug(
                "移除工具调用组",
                assistant_index=group_start,
                group_size=group_end - group_start,
            )
            del working[group_start:group_end]

        return working

    def _remove_oldest_pairs(
        self,
        messages: List[MemoryMessage],
        available_tokens: int,
        token_budget: TokenBudget,
    ) -> List[MemoryMessage]:
        """从最旧开始移除 user+assistant 消息对"""
        working = list(messages)
        while len(working) >= 2:
            current_tokens = token_budget.count_messages_tokens(working)
            if current_tokens <= available_tokens:
                break
            # 找到最旧的一对
            if working[0].role == "user" and working[1].role == "assistant":
                working.pop(0)
                working.pop(0)
            elif working[0].role in ("tool",):
                working.pop(0)
            else:
                working.pop(0)
        return working
