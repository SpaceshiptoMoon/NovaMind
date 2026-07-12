"""
压缩策略接口

当对话 token 数超出预算时，通过压缩策略裁剪上下文。
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from novamind.features.agent.core.memory.interfaces import MemoryMessage
from novamind.features.agent.core.memory.token_budget import TokenBudget


class ICompressionStrategy(ABC):
    """压缩策略接口"""

    @abstractmethod
    async def compress(
        self,
        messages: List[MemoryMessage],
        available_tokens: int,
        token_budget: TokenBudget,
        conversation_id: Optional[int] = None,
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
