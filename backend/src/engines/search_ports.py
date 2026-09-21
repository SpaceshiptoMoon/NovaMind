"""
Web 搜索端口 WebSearchPort，定义 WebSearchResult 数据类。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


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
    ) -> list[WebSearchResult]:
        """执行联网搜索，返回标题/URL/摘要列表。"""
        ...


class ProviderWebSearchPort:
    """``WebSearchPort`` 引擎默认宿主实现：委托已构造的 ``ExternalSearchService``。

    纯 engines 实现，不读 YAML、不 import setting/features；底层 service 由
    ``build_web_search_port_from_provider`` 或宿主装配点显式注入。
    ``service`` 为 ``None`` 时 ``search`` 抛 ``WebSearchError``。
    """

    def __init__(self, service: object | None = None):
        # service 应为 ExternalSearchService 实例。
        self._service = service

    async def search(
        self, query: str, max_results: int = 5
    ) -> list[WebSearchResult]:
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


__all__ = [
    "WebSearchResult",
    "WebSearchPort",
    "ProviderWebSearchPort",
]