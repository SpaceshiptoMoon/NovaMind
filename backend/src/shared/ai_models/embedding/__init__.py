"""
Embedding 客户端包

提供多协议的文本向量化功能，统一接口规范。
支持协议: OpenAI 兼容、Ollama、Transformers 本地推理。
R5 工厂自注册：client 类挂 ``_FACTORY_PROTOCOL`` 入注册表（见 llm/__init__.py 同款）。
"""

from novamind.shared.ai_models.base_model import BaseEmbedding
from novamind.shared.ai_models.embedding.ollama_embedding import OllamaEmbedding
from novamind.shared.ai_models.embedding.openai_compatible import OpenAICompatibleEmbedding
from novamind.shared.ai_models.embedding.transformers_embedding import TransformersEmbedding

OllamaEmbedding._FACTORY_PROTOCOL = "ollama"
OpenAICompatibleEmbedding._FACTORY_PROTOCOL = "openai"
TransformersEmbedding._FACTORY_PROTOCOL = "transformers"

_EMBEDDING_REGISTRY: dict[str, type[BaseEmbedding]] = {
    cls._FACTORY_PROTOCOL: cls  # type: ignore[attr-defined]
    for cls in (OpenAICompatibleEmbedding, OllamaEmbedding, TransformersEmbedding)
}


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
    根据 protocol 从注册表创建对应的 Embedding 客户端

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

    cls = _EMBEDDING_REGISTRY.get(protocol or "")
    if cls is None:
        raise ValueError(f"不支持的 Embedding 协议: {protocol}")
    return cls(**common_kwargs, **kwargs)


__all__ = [
    "BaseEmbedding",
    "OpenAICompatibleEmbedding",
    "OllamaEmbedding",
    "TransformersEmbedding",
    "create_embedding_client",
]