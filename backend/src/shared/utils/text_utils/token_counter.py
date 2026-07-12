"""
Token 计数器

使用 tiktoken 进行 token 计数，支持 OpenAI 风格模型的近似分词。
"""
from typing import Any, Dict, List, Optional

import tiktoken

from novamind.core.middleware.structured_logging import get_logger


_encoders: Dict[str, tiktoken.Encoding] = {}


def _get_encoder(model_name: Optional[str] = None) -> tiktoken.Encoding:
    prefix_map = [
        ("gpt-4o", "o200k_base"),
        ("o1", "o200k_base"),
        ("o3", "o200k_base"),
        ("gpt-4", "cl100k_base"),
        ("gpt-3.5", "cl100k_base"),
        ("claude-", "cl100k_base"),
        ("qwen", "cl100k_base"),
        ("glm-", "cl100k_base"),
        ("ernie-", "cl100k_base"),
        ("deepseek-", "cl100k_base"),
        ("moonshot-", "cl100k_base"),
        ("llama", "cl100k_base"),
    ]

    encoder_name = "cl100k_base"
    if model_name:
        model_lower = model_name.lower()
        for prefix, enc in prefix_map:
            if model_lower.startswith(prefix):
                encoder_name = enc
                break

    if encoder_name not in _encoders:
        _encoders[encoder_name] = tiktoken.get_encoding(encoder_name)
    return _encoders[encoder_name]


class TokenCounter:
    """Token 计数器。"""

    def __init__(self, model_name: str = "gpt-3.5-turbo"):
        self.model_name = model_name
        self.encoder = _get_encoder(model_name)
        self.logger = get_logger(__name__)

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(self.encoder.encode(text))

    def count_messages_tokens(self, messages: List[Dict[str, Any]]) -> int:
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.count_tokens(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        total += self.count_tokens(str(part.get("text", "")))
                    else:
                        total += self.count_tokens(str(part))
            else:
                total += self.count_tokens(str(content))
            total += 4
        return total
