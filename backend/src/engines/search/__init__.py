"""Web 搜索引擎组件包：中立端口 WebSearchPort + 引擎默认实现 + 中立异常。
构造唯一入口在 shared/search/web_search_factory（R3 中心清单），本包只承载契约与默认实现。
"""
from novamind.engines.search.errors import (
    WebSearchError,
    WebSearchProviderAuthError,
    WebSearchProviderNotConfiguredError,
    WebSearchProviderUnavailableError,
)
from novamind.engines.search.ports import (
    ProviderWebSearchPort,
    WebSearchPort,
    WebSearchResult,
)

__all__ = [
    "WebSearchResult",
    "WebSearchPort",
    "ProviderWebSearchPort",
    "WebSearchError",
    "WebSearchProviderAuthError",
    "WebSearchProviderNotConfiguredError",
    "WebSearchProviderUnavailableError",
]
