"""
Rerank 客户端包

提供多协议的文本重排序功能，统一接口规范。
支持协议: OpenAI 兼容、Transformers 本地推理
"""

from src.shared.ai_models.base_model import BaseRerank
from src.shared.ai_models.rerank.openai_rerank import CompatibleRerankClient
from src.shared.ai_models.rerank.transformers_rerank import TransformersRerankClient


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
    根据 protocol 创建对应的 Rerank 客户端

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

    if protocol == "openai":
        return CompatibleRerankClient(**common_kwargs, **kwargs)
    elif protocol == "transformers":
        return TransformersRerankClient(**common_kwargs, **kwargs)

    raise ValueError(f"不支持的 Rerank 协议: {protocol}")


__all__ = [
    "BaseRerank",
    "CompatibleRerankClient",
    "TransformersRerankClient",
    "create_rerank_client",
]
