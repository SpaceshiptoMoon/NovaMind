"""
LLM 客户端包

提供多协议的文本生成功能，统一接口规范。
支持协议: OpenAI 兼容、Anthropic、Ollama、Transformers 本地推理
"""

from src.shared.ai_models.base_model import BaseLLM
from src.shared.ai_models.llm.openai_compatible import OpenAICompatibleLLM
from src.shared.ai_models.llm.anthropic_llm import AnthropicLLM
from src.shared.ai_models.llm.ollama_llm import OllamaLLM
from src.shared.ai_models.llm.transformers_llm import TransformersLLM


def create_llm_client(
    protocol: str,
    api_key: str = "",
    base_url: str = "",
    model_name: str = "",
    timeout: int = 60,
    max_retries: int = 3,
    max_concurrent: int = 10,
    **kwargs,
) -> BaseLLM:
    """
    根据 protocol 创建对应的 LLM 客户端

    Args:
        protocol: 协议类型 (openai / anthropic / ollama / transformers)
        api_key: API 密钥
        base_url: API 基础 URL
        model_name: 模型名称
        timeout: 超时时间（秒）
        max_retries: 最大重试次数
        max_concurrent: 最大并发数
        **kwargs: 协议特定的额外参数

    Returns:
        BaseLLM 实例

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
        return OpenAICompatibleLLM(**common_kwargs, **kwargs)
    elif protocol == "anthropic":
        return AnthropicLLM(**common_kwargs, **kwargs)
    elif protocol == "ollama":
        return OllamaLLM(**common_kwargs, **kwargs)
    elif protocol == "transformers":
        return TransformersLLM(**common_kwargs, **kwargs)

    raise ValueError(f"不支持的 LLM 协议: {protocol}")


__all__ = [
    "BaseLLM",
    "OpenAICompatibleLLM",
    "AnthropicLLM",
    "OllamaLLM",
    "TransformersLLM",
    "create_llm_client",
]
