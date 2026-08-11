"""
Web 搜索端口 WebSearchPort，定义 WebSearchResult 数据类。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol, runtime_checkable


@dataclass
class WebSearchResult:
    """联网搜索单条结果。

    ``content`` / ``score`` 为可选字段（向后兼容：resume/agent 等消费方不读它们；
    deep_research 外部路径用 ``content`` 排序/去重与上下文格式化、用 ``score`` 排序）。
    """

    title: str
    url: str
    snippet: str
    content: str = ""
    score: float = 0.0


@runtime_checkable
class WebSearchPort(Protocol):
    """联网搜索端口：切断消费方对 deep_research 服务的直接依赖。

    供 agent ``web_search`` 工具与 resume 公司背景补充等消费方经依赖注入使用。
    """

    async def search(
        self, query: str, max_results: int = 5
    ) -> List[WebSearchResult]:
        """执行联网搜索，返回标题/URL/摘要列表。"""
        ...


class ProviderWebSearchPort:
    """``WebSearchPort`` 引擎默认宿主实现：委托已构造的 ``ExternalSearchService``。

    纯 engines 实现，不读 YAML、不 import setting/features；底层 service 由
    ``build_web_search_port_from_provider`` 或宿主装配点显式注入。

    与 ``features/deep_research/adapters/web_search_port_adapter.HostWebSearchPort``
    的区别：后者保留无参 YAML DuckDuckGo 兜底语义（供 agent/resume 默认场景）；本类
    无兜底，``service`` 为 ``None`` 时 ``search`` 抛 ``WebSearchError``。
    """

    def __init__(self, service: Optional[object] = None):
        # service 应为 ExternalSearchService 实例。
        self._service = service

    async def search(
        self, query: str, max_results: int = 5
    ) -> List[WebSearchResult]:
        if self._service is None:
            from novamind.engines.search_errors import WebSearchError

            raise WebSearchError("WebSearchPort 未注入底层搜索 service")
        results = await self._service.search(query=query, max_results=max_results)  # type: ignore[attr-defined]
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
        """委托底层 service.close() 释放 HTTP client 等资源（service 未注入时无操作）。"""
        if self._service is None:
            return
        close = getattr(self._service, "close", None)
        if close is None:
            return
        await close()  # type: ignore[misc]


def build_web_search_port_from_provider(
    provider: str,
    api_key: Optional[str],
    extra_config: Optional[dict] = None,
) -> WebSearchPort:
    """按 provider 字符串 + 明文 api_key + extra_config 构造 ``WebSearchPort``。

    纯 engines 层，**不读 YAML**（api_key 由调用方——用户级配置解密后——传入）。
    供宿主按用户级配置构造搜索端口：

    - ``duckduckgo``：忽略 ``api_key``（免费、无需 key）。
    - ``tavily`` / ``serpapi``：无 ``api_key`` 抛
      ``WebSearchProviderNotConfiguredError``。
    - 未知 provider 抛 ``WebSearchProviderNotConfiguredError``。
    - service 不可用（``is_available()`` 返回 False）抛
      ``WebSearchProviderUnavailableError``。

    与 ``features/deep_research/adapters/web_search_port_adapter.build_web_search_port_for_provider``
    的区别：后者按 ``ExternalSearchProvider`` 枚举 + YAML 配置构造（deep_research 每请求注入）；
    本函数按字符串 provider + 显式 api_key 构造（用户级配置注入），不依赖 features/setting。
    """
    from novamind.engines.search_errors import (
        WebSearchProviderNotConfiguredError,
        WebSearchProviderUnavailableError,
    )
    from novamind.shared.config import (
        DuckDuckGoSearchConfig,
        SerpApiSearchConfig,
        TavilySearchConfig,
    )
    from novamind.shared.search.duckduckgo_service import DuckDuckGoSearchService
    from novamind.shared.search.serpapi_service import SerpAPISearchService
    from novamind.shared.search.tavily_service import TavilySearchService

    extra = extra_config or {}
    p = (provider or "").lower()

    if p == "duckduckgo":
        svc = DuckDuckGoSearchService(
            DuckDuckGoSearchConfig(
                max_results=int(extra.get("max_results", 10)),
                timeout=int(extra.get("timeout", 15)),
            )
        )
    elif p == "tavily":
        if not api_key:
            raise WebSearchProviderNotConfiguredError("tavily")
        svc = TavilySearchService(
            TavilySearchConfig(
                api_key=api_key,
                max_results=int(extra.get("max_results", 10)),
                search_depth=str(extra.get("search_depth", "basic")),
                timeout=int(extra.get("timeout", 30)),
            )
        )
    elif p == "serpapi":
        if not api_key:
            raise WebSearchProviderNotConfiguredError("serpapi")
        svc = SerpAPISearchService(
            SerpApiSearchConfig(
                api_key=api_key,
                max_results=int(extra.get("max_results", 10)),
                timeout=int(extra.get("timeout", 30)),
                engine=str(extra.get("engine", "google")),
            )
        )
    else:
        raise WebSearchProviderNotConfiguredError(p or "unknown")

    if not svc.is_available():
        raise WebSearchProviderUnavailableError(p, "服务不可用或未配置")
    return ProviderWebSearchPort(service=svc)  # type: ignore[return-value]


__all__ = [
    "WebSearchResult",
    "WebSearchPort",
    "ProviderWebSearchPort",
    "build_web_search_port_from_provider",
]