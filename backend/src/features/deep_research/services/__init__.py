"""
深度研究模块 - 服务层
"""

from novamind.features.deep_research.services.external_search_service import (
    ExternalSearchService,
    ExternalSearchResult,
)
from novamind.features.deep_research.services.tavily_service import TavilySearchService
from novamind.features.deep_research.services.serpapi_service import SerpAPISearchService
from novamind.features.deep_research.services.duckduckgo_service import DuckDuckGoSearchService
from novamind.features.deep_research.services.deep_research_service import DeepResearchService

__all__ = [
    "ExternalSearchService",
    "ExternalSearchResult",
    "TavilySearchService",
    "SerpAPISearchService",
    "DuckDuckGoSearchService",
    "DeepResearchService",
]
