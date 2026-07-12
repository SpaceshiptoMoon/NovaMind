"""
Embedding 客户端包

提供多协议的文本向量化功能，统一接口规范。
支持协议: OpenAI 兼容、Ollama、Transformers 本地推理
"""

from novamind.shared.ai_models.base_model import BaseEmbedding
from novamind.shared.ai_models.embedding.openai_compatible import OpenAICompatibleEmbedding
from novamind.shared.ai_models.embedding.ollama_embedding import OllamaEmbedding
from novamind.shared.ai_models.embedding.transformers_embedding import TransformersEmbedding
from novamind.shared.ai_models.embedding.multimodal_embedding import BaseMultimodalEmbedding
from novamind.shared.ai_models.embedding.openai_compatible_multimodal import OpenAICompatibleMultimodalEmbedding
from novamind.shared.ai_models.embedding.dashscope_multimodal import DashScopeMultimodalEmbedding


def create_embedding_client(
    protocol: str,
    api_key: str = "",
    base_url: str = "",
    model_name: str = "",
    expected_dimension: int | None = None,
    timeout: int = 60,
    max_retries: int = 3,
    max_concurrent: int = 5,
    **kwargs,
) -> BaseEmbedding:
    """
    根据 protocol 创建对应的 Embedding 客户端

    Args:
        protocol: 协议类型 (openai / ollama / transformers)
        api_key: API 密钥
        base_url: API 基础 URL
        model_name: 模型名称
        expected_dimension: 期望的向量维度
        timeout: 超时时间（秒）
        max_retries: 最大重试次数
        max_concurrent: 最大并发数

    Returns:
        BaseEmbedding 实例

    Raises:
        ValueError: 不支持的 protocol
    """
    common_kwargs = {
        "api_key": api_key,
        "base_url": base_url,
        "model_name": model_name,
        "expected_dimension": expected_dimension,
        "timeout": timeout,
        "max_retries": max_retries,
        "max_concurrent": max_concurrent,
    }

    if protocol == "openai":
        return OpenAICompatibleEmbedding(**common_kwargs, **kwargs)
    elif protocol == "ollama":
        return OllamaEmbedding(**common_kwargs, **kwargs)
    elif protocol == "transformers":
        return TransformersEmbedding(**common_kwargs, **kwargs)
    elif protocol == "multimodal_openai":
        return OpenAICompatibleMultimodalEmbedding(**common_kwargs, **kwargs)
    elif protocol == "dashscope_multimodal":
        return DashScopeMultimodalEmbedding(**common_kwargs, **kwargs)

    raise ValueError(f"不支持的 Embedding 协议: {protocol}")


__all__ = [
    "BaseEmbedding",
    "BaseMultimodalEmbedding",
    "OpenAICompatibleEmbedding",
    "OpenAICompatibleMultimodalEmbedding",
    "DashScopeMultimodalEmbedding",
    "OllamaEmbedding",
    "TransformersEmbedding",
    "create_embedding_client",
]
