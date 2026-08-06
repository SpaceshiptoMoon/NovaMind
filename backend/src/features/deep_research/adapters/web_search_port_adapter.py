"""
WebSearchPort 宿主适配器，归一化搜索 provider 结果为引擎端口格式。

读 setting 择优构造 provider，消费方经依赖注入消费。
"""
from typing import List, Optional

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
            from novamind.shared.clients.search.duckduckgo_service import (
                DuckDuckGoSearchService,
            )

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
    ) -> List[WebSearchResult]:
        service = await self._ensure_service()
        results = await service.search(query=query, max_results=max_results)  # type: ignore[attr-defined]
        return [
            WebSearchResult(
                title=getattr(r, "title", "") or "",
                url=getattr(r, "url", "") or "",
                snippet=getattr(r, "content", "") or "",
            )
            for r in results
        ]


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
        from novamind.shared.clients.search.tavily_service import (
            TavilySearchService,
        )

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

    from novamind.shared.clients.search.duckduckgo_service import (
        DuckDuckGoSearchService,
    )

    svc = DuckDuckGoSearchService(
        DuckDuckGoSearchConfig(
            max_results=es_cfg.duckduckgo.max_results,
            timeout=es_cfg.duckduckgo.timeout,
        )
    )
    return HostWebSearchPort(service=svc)  # type: ignore[return-value]