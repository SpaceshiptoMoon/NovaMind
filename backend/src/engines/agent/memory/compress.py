"""
压缩策略接口

当对话 token 数超出预算时，通过压缩策略裁剪上下文。
"""
from abc import ABC, abstractmethod

from novamind.engines.agent.memory.interfaces import MemoryMessage
from novamind.engines.agent.memory.token_budget import TokenBudget


class ICompressionStrategy(ABC):
    """压缩策略接口"""

    @abstractmethod
    async def compress(
        self,
        messages: list[MemoryMessage],
        available_tokens: int,
        token_budget: TokenBudget,
        conversation_id: int | None = None,
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
    ) -> tuple[list[MemoryMessage], bool, float]:
        """
        压缩消息列表以适应 token 预算

        Args:
            messages: 原始消息列表
            available_tokens: 可用 token 预算
            token_budget: Token 计数器
            conversation_id: 会话 ID（摘要持久化与记忆提取用），可空。
            system_prompt: 当前请求的 system prompt 全文，可空。摘要 LLM 调用
                以它 + tools 重放请求前缀，使命中 provider KV cache 成为可能
                （前缀缓存对齐压缩）；None 时降级独立摘要 prompt。
            tools: 当前请求的 OpenAI tools schema 列表，可空。与 system_prompt
                配对使用，两者任一缺失即走独立摘要 prompt 路径。

        Returns:
            (压缩后消息列表, 是否发生压缩, 压缩比率)
        """
        ...
