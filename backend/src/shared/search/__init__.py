"""
外部搜索客户端，包含 DuckDuckGo、Tavily、SerpAPI 搜索 provider 的 HTTP 客户端实现。
"""
from novamind.shared.search.external_search_service import (
    ExternalSearchResult,
    ExternalSearchService,
)
from novamind.shared.search.duckduckgo_service import DuckDuckGoSearchService
from novamind.shared.search.tavily_service import TavilySearchService
from novamind.shared.search.serpapi_service import SerpAPISearchService

__all__ = [
    "ExternalSearchService",
    "ExternalSearchResult",
    "DuckDuckGoSearchService",
    "TavilySearchService",
    "SerpAPISearchService",
]