"""
deep_research 外部数据源（SearchSourcePort）实现。

- ``WebSearchSourceAdapter``：包装 ``WebSearchPort`` 满足引擎统一 ``SearchSourcePort``
  （归一化 ``WebSearchResult`` → 统一 dict：source_type=external，content/url/title/score），
  外部数据源接入点；``close`` 委托底层 port 释放 HTTP client。
- ``build_web_search_source(ctx)``：数据源注册表工厂。provider 构造委托
  ``shared/search/web_search_factory.build_web_search_port_from_provider``（R3 唯一构造点），
  本函数只负责 YAML 凭据提取、请求级 ``search_depth`` 合并、以及中立异常到 feature
  异常的镜像映射（``WebSearchProviderNotConfiguredError`` → ``SearchProviderNotConfiguredError``）。
"""
from typing import Any

from novamind.engines.deep_research.sources import (
    SearchSourceContext,
    SearchSourcePort,
)
from novamind.engines.deep_research.types import SourceType
from novamind.engines.search_errors import (
    WebSearchError,
    WebSearchProviderNotConfiguredError,
    WebSearchProviderUnavailableError,
)
from novamind.engines.search_ports import WebSearchPort
from novamind.features.deep_research.exceptions import (
    SearchProviderNotConfiguredError,
    SearchProviderUnavailableError,
)
from novamind.shared.search.web_search_factory import (
    build_web_search_port_from_provider,
)


class WebSearchSourceAdapter:
    """外部 Web 数据源适配器：包装 ``WebSearchPort`` 满足引擎统一 ``SearchSourcePort``。

    归一化在此完成：``WebSearchResult`` → 统一 dict（source_type=external，
    content/url/title/score），引擎循环透传 dict。
    """

    def __init__(self, web_port: WebSearchPort):
        self._web_port = web_port

    async def search(self, query: str, *, top_k: int) -> list[dict[str, Any]]:
        raw = await self._web_port.search(query, max_results=top_k)
        return [
            {
                "source_type": SourceType.EXTERNAL.value,
                "content": getattr(r, "content", "") or getattr(r, "snippet", ""),
                "url": getattr(r, "url", ""),
                "title": getattr(r, "title", ""),
                "score": getattr(r, "score", 0.0),
            }
            for r in raw
        ]

    async def close(self) -> None:
        """委托底层 port 释放 HTTP client 等资源。"""
        close = getattr(self._web_port, "close", None)
        if close is not None:
            await close()  # type: ignore[misc]


def _yaml_credentials(provider: str, search_depth: str) -> tuple[str | None, dict[str, Any]]:
    """从 YAML external_search 段提取 provider 凭据与 extra（读配置，不构造）。

    请求级 ``search_depth`` 合并进 tavily 的 extra（覆盖 YAML 默认）。
    """
    from novamind.setting.yaml_config import get_config

    es_cfg = get_config().external_search
    if provider == "tavily":
        return es_cfg.tavily.api_key, {
            "max_results": es_cfg.tavily.max_results,
            "search_depth": search_depth,
            "timeout": es_cfg.tavily.timeout,
        }
    if provider == "serpapi":
        return es_cfg.serpapi.api_key, {
            "max_results": es_cfg.serpapi.max_results,
            "timeout": es_cfg.serpapi.timeout,
            "engine": es_cfg.serpapi.engine,
        }
    # duckduckgo 免 key
    return None, {
        "max_results": es_cfg.duckduckgo.max_results,
        "timeout": es_cfg.duckduckgo.timeout,
    }


def build_web_search_source(context: SearchSourceContext) -> SearchSourcePort:
    """外部数据源注册表工厂：按 ctx.config（ExternalSearchConfig dump）构造。

    provider 构造/校验/is_available 全部在共享工厂（R3 唯一实现）；本函数补两件事：
    YAML 凭据提取（含请求级 search_depth 合并）与中立异常 → feature 异常镜像。
    """
    config = context.config or {}
    provider = str(config.get("provider") or "duckduckgo").lower()
    from novamind.setting.yaml_config import get_config

    es_cfg = get_config().external_search
    # 请求级 search_depth（basic/advanced），缺省回落 YAML 配置
    search_depth = str(config.get("search_depth") or es_cfg.tavily.search_depth or "basic")

    api_key, extra = _yaml_credentials(provider, search_depth)
    try:
        port = build_web_search_port_from_provider(provider, api_key, extra)
    except WebSearchProviderNotConfiguredError:
        raise SearchProviderNotConfiguredError(provider) from None
    except WebSearchProviderUnavailableError as e:
        raise SearchProviderUnavailableError(provider, e.reason) from None
    except WebSearchError as e:
        raise SearchProviderUnavailableError(provider, str(e)) from None
    return WebSearchSourceAdapter(port)


__all__ = [
    "WebSearchSourceAdapter",
    "build_web_search_source",
]
