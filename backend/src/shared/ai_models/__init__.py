"""
AI 模型客户端统一入口

提供 LLM、Embedding、Rerank 客户端的统一导入。
支持协议: openai / anthropic / ollama / transformers
"""

from novamind.shared.ai_models.base_model import BaseEmbedding, BaseLLM, BaseRerank
from novamind.shared.ai_models.embedding import (
    OllamaEmbedding,
    OpenAICompatibleEmbedding,
    TransformersEmbedding,
)
from novamind.shared.ai_models.llm import (
    AnthropicLLM,
    OllamaLLM,
    OpenAICompatibleLLM,
    TransformersLLM,
)
from novamind.shared.ai_models.rerank import CompatibleRerankClient, TransformersRerankClient

__all__ = [
    "BaseLLM",
    "BaseEmbedding",
    "BaseRerank",
    "OpenAICompatibleLLM",
    "AnthropicLLM",
    "OllamaLLM",
    "TransformersLLM",
    "OpenAICompatibleEmbedding",
    "OllamaEmbedding",
    "TransformersEmbedding",
    "CompatibleRerankClient",
    "TransformersRerankClient",
]
