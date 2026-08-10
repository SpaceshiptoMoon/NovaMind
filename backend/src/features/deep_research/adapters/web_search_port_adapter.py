"""
WebSearchPort 宿主适配器，归一化搜索 provider 结果为引擎端口格式。

读 setting 择优构造 provider，消费方经依赖注入消费。

- ``HostWebSearchPort``：委托任意 ExternalSearchService；``search`` 填充 ``content``/``score``
  （deep_research 外部路径用），``close`` 委托底层 service.close()。
- ``build_web_search_port()``：按 setting 择优（Tavily > DuckDuckGo 兜底），供 resume/agent。
- ``build_web_search_port_for_provider(provider)``：按指定 provider 构造（Tavily/SerpAPI/DDG），
  供 deep_research 每请求注入。
"""
from typing import Optional

from novamind.engines.search_ports import WebSearchPort, WebSearchResult


class HostWebSearchPort:
    """WebSearchPort 宿主实现：委托任意 ExternalSearchService 实例。"""

    def __init__(self, service: Optional[object] = None):
        # service 应为 ExternalSearchService 实例；延迟构造避免启动期强依赖配置。
        self._service = service

    async def _ensure_service(self) -> object:
        if self._service is None:
            # 默认回退到 DuckDuckGo（免费、无需 API Key）
            from novamind.setting.yaml_config import get_config
            from novamind.shared.config import DuckDuckGoSearchConfig
            from novamind.shared.search.duckduckgo_service import DuckDuckGoSearchService

            ddg = get_config().external_search.duckduckgo
            self._service = DuckDuckGoSearchService(
                DuckDuckGoSearchConfig(
                    max_results=ddg.max_results,
                    timeout=ddg.timeout,
                )
            )
        return self._service

    async def search(
        self, query: str, max_results: int = 5
    ) -> list[WebSearchResult]:
        service = await self._ensure_service()
        results = await service.search(query=query, max_results=max_results)  # type: ignore[attr-defined]
        return [
            WebSearchResult(
                title=getattr(r, "title", "") or "",
                url=getattr(r, "url", "") or "",
                snippet=getattr(r, "content", "") or "",
                content=getattr(r, "content", "") or "",
                score=float(getattr(r, "score", 0.0) or 0.0),
            )
            for r in results
        ]

    async def close(self) -> None:
        """委托底层 service.close() 释放 HTTP client 等资源（service 未构造时无操作）。"""
        if self._service is None:
            return
        close = getattr(self._service, "close", None)
        if close is None:
            return
        await close()  # type: ignore[misc]


def as_web_search_port(service: Optional[object] = None) -> WebSearchPort:
    """构造 WebSearchPort 实例（供装配点注入 context）。"""
    return HostWebSearchPort(service=service)  # type: ignore[return-value]


def build_web_search_port(prefer_tavily: bool = True) -> WebSearchPort:
    """按 ``setting.external_search`` 配置择优构造 WebSearchPort。

    优先级：Tavily（配了 api_key 且 ``prefer_tavily``）> DuckDuckGo（免费兜底）。
    供 agent web_search 工具与 resume 等消费方注入，避免各自直接 import
    deep_research 搜索服务。
    """
    from novamind.setting.yaml_config import get_config
    from novamind.shared.config import DuckDuckGoSearchConfig, TavilySearchConfig

    es_cfg = get_config().external_search

    if prefer_tavily and es_cfg.tavily.api_key:
        from novamind.shared.search.tavily_service import TavilySearchService

        svc = TavilySearchService(
            TavilySearchConfig(
                api_key=es_cfg.tavily.api_key,
                max_results=es_cfg.tavily.max_results,
                search_depth=es_cfg.tavily.search_depth,
                timeout=es_cfg.tavily.timeout,
            )
        )
        if svc.is_available():
            return HostWebSearchPort(service=svc)  # type: ignore[return-value]

    from novamind.shared.search.duckduckgo_service import DuckDuckGoSearchService

    svc = DuckDuckGoSearchService(
        DuckDuckGoSearchConfig(
            max_results=es_cfg.duckduckgo.max_results,
            timeout=es_cfg.duckduckgo.timeout,
        )
    )
    return HostWebSearchPort(service=svc)  # type: ignore[return-value]


def build_web_search_port_for_provider(provider) -> WebSearchPort:
    """按指定 ``ExternalSearchProvider`` 构造 WebSearchPort（deep_research 每请求注入）。

    支持 Tavily / SerpAPI / DuckDuckGo。provider 未配置 api_key →
    ``SearchProviderNotConfiguredError``；service 不可用 →
    ``SearchProviderUnavailableError``。
    """
    from novamind.setting.yaml_config import get_config
    from novamind.shared.config import (
        DuckDuckGoSearchConfig,
        SerpApiSearchConfig,
        TavilySearchConfig,
    )
    from novamind.shared.search.duckduckgo_service import DuckDuckGoSearchService
    from novamind.shared.search.serpapi_service import SerpAPISearchService
    from novamind.shared.search.tavily_service import TavilySearchService
    from novamind.features.deep_research.exceptions import (
        SearchProviderNotConfiguredError,
        SearchProviderUnavailableError,
    )
    from novamind.features.deep_research.models.research_session import (
        ExternalSearchProvider,
    )

    es_cfg = get_config().external_search

    if provider == ExternalSearchProvider.TAVILY:
        if not es_cfg.tavily.api_key:
            raise SearchProviderNotConfiguredError(provider.value)
        svc = TavilySearchService(
            TavilySearchConfig(
                api_key=es_cfg.tavily.api_key,
                max_results=es_cfg.tavily.max_results,
                search_depth=es_cfg.tavily.search_depth,
                timeout=es_cfg.tavily.timeout,
            )
        )
    elif provider == ExternalSearchProvider.SERPAPI:
        if not es_cfg.serpapi.api_key:
            raise SearchProviderNotConfiguredError(provider.value)
        svc = SerpAPISearchService(
            SerpApiSearchConfig(
                api_key=es_cfg.serpapi.api_key,
                max_results=es_cfg.serpapi.max_results,
                timeout=es_cfg.serpapi.timeout,
                engine=es_cfg.serpapi.engine,
            )
        )
    elif provider == ExternalSearchProvider.DUCKDUCKGO:
        svc = DuckDuckGoSearchService(
            DuckDuckGoSearchConfig(
                max_results=es_cfg.duckduckgo.max_results,
                timeout=es_cfg.duckduckgo.timeout,
            )
        )
    else:
        raise SearchProviderNotConfiguredError(
            getattr(provider, "value", str(provider))
        )

    if not svc.is_available():
        raise SearchProviderUnavailableError(
            getattr(provider, "value", str(provider)), "服务不可用或未配置"
        )
    return HostWebSearchPort(service=svc)  # type: ignore[return-value]


__all__ = [
    "HostWebSearchPort",
    "as_web_search_port",
    "build_web_search_port",
    "build_web_search_port_for_provider",
]