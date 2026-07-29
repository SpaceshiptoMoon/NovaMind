"""
WebSearchPort 宿主适配器

包 `deep_research.services.duckduckgo_service.DuckDuckGoSearchService`，
将其 `ExternalSearchResult` 归一化为引擎端口定义的 `WebSearchResult`。

引擎侧 `web_search` 工具不再直接 import deep_research 服务，改经
`context["web_search_port"]` 调用本适配器。
"""
from typing import List, Optional

from novamind.features.agent.core.ports import WebSearchPort, WebSearchResult


class HostWebSearchPort:
    """WebSearchPort 宿主实现：委托 DuckDuckGoSearchService。"""

    def __init__(self, service: Optional[object] = None):
        # 延迟构造避免启动期强依赖 deep_research 配置
        self._service = service

    async def _ensure_service(self) -> object:
        if self._service is None:
            from novamind.features.deep_research.services.duckduckgo_service import (
                DuckDuckGoSearchService,
            )

            self._service = DuckDuckGoSearchService()
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