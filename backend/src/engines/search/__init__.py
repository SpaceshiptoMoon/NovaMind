"""外部搜索引擎——Web 搜索 provider 的纯逻辑实现。

零 ``features`` / ``setting`` / ORM 依赖；配置经 ``shared.config`` dataclass 注入，
日志经 ``shared.logging``。由 ``features/deep_research`` 装配点（读 setting、择优 provider）
实例化，消费方（agent ``web_search`` 工具、resume 公司背景补充、qa 联网搜索等）经
``WebSearchPort``（见 ``engines/search_ports.py``）依赖注入消费。

组件：
  external_search_service   ExternalSearchService ABC + ExternalSearchResult dataclass
  duckduckgo_service         DuckDuckGo 搜索（免费兜底，无需 API Key）
  tavily_service             Tavily 搜索（AI 优化，需 API Key）
  serpapi_service            SerpAPI 搜索（Google 结果，需 API Key）
"""
from novamind.engines.search.external_search_service import (
    ExternalSearchResult,
    ExternalSearchService,
)
from novamind.engines.search.duckduckgo_service import DuckDuckGoSearchService
from novamind.engines.search.tavily_service import TavilySearchService
from novamind.engines.search.serpapi_service import SerpAPISearchService

__all__ = [
    "ExternalSearchService",
    "ExternalSearchResult",
    "DuckDuckGoSearchService",
    "TavilySearchService",
    "SerpAPISearchService",
]