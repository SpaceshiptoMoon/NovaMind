"""
Token 计数器

使用 tiktoken 进行 token 计数，支持 OpenAI 模型的标准分词器。
"""
from typing import List, Dict, Any, Optional
import tiktoken

from src.core.middleware.structured_logging import get_logger


# 缓存编码器实例，避免重复创建
_encoders: Dict[str, tiktoken.Encoding] = {}


def _get_encoder(model_name: Optional[str] = None) -> tiktoken.Encoding:
    """
    根据模型名称获取合适的分词器

    Args:
        model_name: 模型名称

    Returns:
        tiktoken.Encoding 对应的编码器实例
    """
    # 模型名称前缀到编码器的映射（前缀匹配，覆盖所有变体）
    prefix_map = [
        ("gpt-4", "cl100k_base"),
        ("gpt-3.5", "cl100k_base"),
        ("gpt-4o", "cl100k_base"),
        ("claude-", "cl100k_base"),
        ("qwen", "cl100k_base"),
        ("glm-", "cl100k_base"),
        ("ernie-", "cl100k_base"),
        ("deepseek-", "cl100k_base"),
        ("moonshot-", "cl100k_base"),
        ("llama", "cl100k_base"),
    ]

    # 通过前缀匹配获取编码器名称
    encoder_name = "cl100k_base"
    if model_name:
        model_lower = model_name.lower()
        for prefix, enc in prefix_map:
            if model_lower.startswith(prefix):
                encoder_name = enc
                break

    # 从缓存获取或创建新的编码器
    if encoder_name not in _encoders:
        _encoders[encoder_name] = tiktoken.get_encoding(encoder_name)

    return _encoders[encoder_name]


class TokenCounter:
    """Token 计数器，使用 tiktoken 计算 token 数"""

    def __init__(self, model_name: str = "gpt-3.5-turbo"):
        self.model_name = model_name
        self.encoder = _get_encoder(model_name)
        self.logger = get_logger(__name__)

    def count_tokens(self, text: str) -> int:
        """
        计算文本的 token 数

        Args:
            text: 要计算的文本

        Returns:
            token 数量
        """
        if not text:
            return 0
        return len(self.encoder.encode(text))

    def count_messages_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """
        计算消息列表的总 token 数

        包括角色标记，每条消息按固定格式计算
        格式: {"role": "user/assistant", "content": "..."}

        Args:
            messages: 消息列表，每条消息必须包含 role 和 content

        Returns:
            总 token 数
        """
        total = 0
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if not role or not content:
                self.logger.warning("消息缺少 role 或 content 字段", message=msg)
                continue

            # 角色占用的 token（约 4 个）
            total += 4
            # 内容占用的 token
            total += self.count_tokens(content)

        return total

    def estimate_messages_tokens(self, message_count: int) -> int:
        """
        快速估算消息列表 token 数（不编码）

        Args:
            message_count: 消息数量

        Returns:
            估算的 token 数
        """
        # 每条消息平均约 100 个 token
        return message_count * 100

    def get_encoder(self) -> tiktoken.Encoding:
        """获取编码器实例"""
        return self.encoder
