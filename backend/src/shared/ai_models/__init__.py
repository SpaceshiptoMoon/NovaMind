"""
AI 模型客户端统一入口

提供 LLM、Embedding、Rerank 客户端的统一导入。
支持协议: openai / anthropic / ollama / transformers
"""

from novamind.shared.ai_models.base_model import BaseLLM, BaseEmbedding, BaseRerank
from novamind.shared.ai_models.llm import OpenAICompatibleLLM, AnthropicLLM, OllamaLLM
from novamind.shared.ai_models.llm import TransformersLLM
from novamind.shared.ai_models.embedding import OpenAICompatibleEmbedding, OllamaEmbedding
from novamind.shared.ai_models.embedding import TransformersEmbedding
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
