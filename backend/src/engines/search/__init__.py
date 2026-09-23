"""Web 搜索引擎组件包：中立端口 WebSearchPort + 引擎默认实现 + 中立异常。

原 engines 顶层散件 search_ports.py / search_errors.py 收编成包（与 rag/eval/
deep_research 等按引擎分目录的组织方式一致）。构造唯一入口是
``shared/search/web_search_factory``（R3 中心清单）；本包只承载契约与默认实现。
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
