"""
Rerank 客户端包

提供多协议的文本重排序功能，统一接口规范。
支持协议: OpenAI 兼容、Transformers 本地推理。
R5 工厂自注册：client 类挂 ``_FACTORY_PROTOCOL`` 入注册表（见 llm/__init__.py 同款）。
"""

from novamind.shared.ai_models.base_model import BaseRerank
from novamind.shared.ai_models.rerank.openai_rerank import CompatibleRerankClient
from novamind.shared.ai_models.rerank.transformers_rerank import TransformersRerankClient

CompatibleRerankClient._FACTORY_PROTOCOL = "openai"
TransformersRerankClient._FACTORY_PROTOCOL = "transformers"

_RERANK_REGISTRY: dict[str, type[BaseRerank]] = {
    cls._FACTORY_PROTOCOL: cls  # type: ignore[attr-defined]
    for cls in (CompatibleRerankClient, TransformersRerankClient)
}


def create_rerank_client(
    protocol: str,
    api_key: str = "",
    base_url: str = "",
    model_name: str = "",
    timeout: int = 30,
    max_retries: int = 3,
    max_concurrent: int = 5,
    **kwargs,
) -> BaseRerank:
    """
    根据 protocol 从注册表创建对应的 Rerank 客户端

    Args:
        protocol: 协议类型 (openai / transformers)
        api_key: API 密钥
        base_url: API 基础 URL
        model_name: 模型名称
        timeout: 超时时间（秒）
        max_retries: 最大重试次数
        max_concurrent: 最大并发数
        **kwargs: 协议特定的额外参数（如 openai 的 endpoint）

    Returns:
        BaseRerank 实例

    Raises:
        ValueError: 不支持的 protocol
    """
    common_kwargs = {
        "api_key": api_key,
        "base_url": base_url,
        "model_name": model_name,
        "timeout": timeout,
        "max_retries": max_retries,
        "max_concurrent": max_concurrent,
    }

    cls = _RERANK_REGISTRY.get(protocol or "")
    if cls is None:
        raise ValueError(f"不支持的 Rerank 协议: {protocol}")
    return cls(**common_kwargs, **kwargs)


__all__ = [
    "BaseRerank",
    "CompatibleRerankClient",
    "TransformersRerankClient",
    "create_rerank_client",
]
