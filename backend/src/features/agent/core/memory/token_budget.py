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
        from src.shared.utils.text_processing.token_counter import TokenCounter
        self._counter = TokenCounter(model_name)

    def count_text_tokens(self, text: str) -> int:
        """计算文本 token 数"""
        return self._counter.count_tokens(text)

    def count_messages_tokens(
        self, messages: List[MemoryMessage]
    ) -> int:
        """
        计算消息列表的 token 数

        每条消息包含约 4 个 token 的角色标记开销，
        tool_calls / tool_call_id / tool_name 的额外开销也计入。
        """
        total = 0
        for msg in messages:
            total += 4  # 角色标记开销
            if msg.content:
                if isinstance(msg.content, str):
                    total += self.count_text_tokens(msg.content)
                elif isinstance(msg.content, list):
                    for part in msg.content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            total += self.count_text_tokens(part.get("text", ""))
                        elif isinstance(part, dict) and part.get("type") == "image_url":
                            total += 85  # approximate image token cost
            if msg.tool_calls:
                total += self.count_text_tokens(
                    json.dumps(msg.tool_calls, ensure_ascii=False)
                )
            if msg.tool_call_id:
                total += 6  # tool_call_id 格式开销
            if msg.tool_name:
                total += 3  # tool_name 格式开销
        return total
