"""外部搜索客户端——Web 搜索 provider 的 HTTP 客户端实现。

定位为 ``shared/`` 基础能力：每个 provider 是对外部 SaaS / 公开接口的 HTTP 客户端
（一次请求 + 结果归一化），无多步编排。零 ``features`` / ``setting`` / ORM 依赖；
配置经 ``shared.config`` dataclass 注入，日志经 ``shared.logging``。

编排归属：
  - 引擎层端口 ``WebSearchPort`` / ``WebSearchResult`` 定义在 ``engines/search_ports.py``
    （端口在 engines，实现在 shared，同 ``CachePort``/``RedisCache`` 约定）。
  - 读 ``setting`` 择优 provider 的装配（``build_web_search_port``）归属
    ``features/deep_research/adapters/``（feature 层可读 setting）。
  - 真正的深研编排（query → 搜索 → LLM 摘要 → 迭代）在 ``features/deep_research`` 业务层。

组件：
  external_search_service   ExternalSearchService ABC + ExternalSearchResult dataclass
  duckduckgo_service         DuckDuckGo 搜索（免费兜底，无需 API Key）
  tavily_service             Tavily 搜索（AI 优化，需 API Key）
  serpapi_service            SerpAPI 搜索（Google 结果，需 API Key）
"""
from novamind.shared.clients.search.external_search_service import (
    ExternalSearchResult,
    ExternalSearchService,
)
from novamind.shared.clients.search.duckduckgo_service import DuckDuckGoSearchService
from novamind.shared.clients.search.tavily_service import TavilySearchService
from novamind.shared.clients.search.serpapi_service import SerpAPISearchService

__all__ = [
    "ExternalSearchService",
    "ExternalSearchResult",
    "DuckDuckGoSearchService",
    "TavilySearchService",
    "SerpAPISearchService",
]