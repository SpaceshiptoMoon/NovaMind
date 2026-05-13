"""
深度研究模块 - 服务层
"""

from src.features.deep_research.services.external_search_service import (
    ExternalSearchService,
    ExternalSearchResult,
)
from src.features.deep_research.services.tavily_service import TavilySearchService
from src.features.deep_research.services.serpapi_service import SerpAPISearchService
from src.features.deep_research.services.duckduckgo_service import DuckDuckGoSearchService
from src.features.deep_research.services.deep_research_service import DeepResearchService

__all__ = [
    "ExternalSearchService",
    "ExternalSearchResult",
    "TavilySearchService",
    "SerpAPISearchService",
    "DuckDuckGoSearchService",
    "DeepResearchService",
]
