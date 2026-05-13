"""
Token 预算管理器

封装 token 计数逻辑，为记忆系统提供预算计算能力。
复用 src/shared/utils/text_processing/token_counter.py。
"""
import json
from typing import List

from src.features.agent.core.memory.interfaces import MemoryMessage


class TokenBudget:
    """
    Token 预算管理器

    提供：
    - 文本 token 计数
    - 消息列表 token 计数（含角色标记和 tool_calls 开销）
    - 可用预算计算（考虑 system_prompt / tools / 生成预留）
    """

    def __init__(self, model_name: str = "gpt-4"):
        self._model_name = model_name

    def count_text_tokens(self, text: str) -> int:
        """计算文本 token 数"""
        from src.shared.utils.text_processing.token_counter import TokenCounter

        counter = TokenCounter(self._model_name)
        return counter.count_tokens(text)

    def count_messages_tokens(
        self, messages: List[MemoryMessage]
    ) -> int:
        """
        计算消息列表的 token 数

        每条消息包含约 4 个 token 的角色标记开销，
        tool_calls 的 JSON 额外计入。
        """
        total = 0
        for msg in messages:
            total += 4  # 角色标记开销
            if msg.content:
                total += self.count_text_tokens(msg.content)
            if msg.tool_calls:
                total += self.count_text_tokens(
                    json.dumps(msg.tool_calls, ensure_ascii=False)
                )
        return total

    def get_available_budget(
        self,
        model_context_window: int,
        system_prompt_tokens: int,
        tools_tokens: int,
        reserve_for_generation: int = 1024,
    ) -> int:
        """
        计算可用于历史消息的 token 预算

        公式：context_window - system_prompt - tools - reserve
        """
        available = (
            model_context_window
            - system_prompt_tokens
            - tools_tokens
            - reserve_for_generation
        )
        return max(available, 0)
