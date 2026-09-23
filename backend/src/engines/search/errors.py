"""
联网搜索引擎中立异常类。

引擎内部预期错误继承 ``WebSearchError``；宿主装配点捕获后映射为对应宿主
``BaseAPIError``（如 features/user 的 ``SearchConfigTestFailedError``）。与
``engines/rag/errors.py`` 同构：engines 层只抛中立异常，不依赖宿主异常体系，
由 features 装配点决定如何呈现给 API 调用方。
"""
from __future__ import annotations

__all__ = [
    "WebSearchError",
    "WebSearchProviderAuthError",
    "WebSearchProviderNotConfiguredError",
    "WebSearchProviderUnavailableError",
]


class WebSearchError(Exception):
    """联网搜索引擎中立异常基类。

    引擎内部一切预期错误继承此类。宿主装配点捕获后映射为对应宿主 ``BaseAPIError``。
    """


class WebSearchProviderAuthError(WebSearchError):
    """搜索服务商拒绝凭证（HTTP 401/403）——api_key 无效或权限不足。

    与「未配置」「暂不可用」区分开：凭证错误是确定性的配置错误，必须
    向上层传播（如搜索配置「测试连接」据此报失败），不得静默降级为空结果。
    """

    def __init__(self, provider: str, status_code: int | None = None):
        detail = f" (HTTP {status_code})" if status_code else ""
        super().__init__(f"外部搜索服务商 {provider} 凭证无效或被拒绝{detail}")
        self.provider = provider
        self.status_code = status_code


class WebSearchProviderNotConfiguredError(WebSearchError):
    """搜索服务商未配置（缺 api_key 或未知 provider）。"""

    def __init__(self, provider: str):
        super().__init__(f"外部搜索服务商 {provider} 未配置 API Key")
        self.provider = provider


class WebSearchProviderUnavailableError(WebSearchError):
    """搜索服务商不可用（service.is_available() 返回 False）。"""

    def __init__(self, provider: str, reason: str = "服务不可用或未配置"):
        super().__init__(f"外部搜索服务商 {provider} 不可用: {reason}")
        self.provider = provider
        self.reason = reason