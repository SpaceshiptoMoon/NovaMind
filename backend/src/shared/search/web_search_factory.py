"""web 搜索端口唯一构造工厂（批次 2.1 收敛）。

此前同样的「按 provider 构造搜索客户端」逻辑有四份逐字级重复：
engines/search_ports.build_web_search_port_from_provider、
deep_research/adapters/web_search_port_adapter 的三个 build_*、
qa/ai_chat_service 的 _resolve/_build_yaml_fallback。本模块成为唯一实现，
消费方全部改调此处。

语义保持（择优链）：
1. 用户显式指定 provider → 该 provider 的用户配置（SearchConfigService 解密凭据）
2. 用户首选（is_primary）→ 同上
3. YAML 全局默认（Tavily 配了 api_key 则优先）→ DuckDuckGo 兜底

R5 工厂自注册：各 provider 构造器挂 ``_FACTORY_NAME`` 属性 + 模块扫描入注册表，
新增 provider 无需改本文件分支链。
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.search_errors import (
    WebSearchError,
    WebSearchProviderNotConfiguredError,
    WebSearchProviderUnavailableError,
)
from novamind.engines.search_ports import (
    ProviderWebSearchPort,
    WebSearchPort,
    WebSearchResult,
)
from novamind.shared.config import (
    DuckDuckGoSearchConfig,
    SerpApiSearchConfig,
    TavilySearchConfig,
)
from novamind.shared.search.duckduckgo_service import DuckDuckGoSearchService
from novamind.shared.search.serpapi_service import SerpAPISearchService
from novamind.shared.search.tavily_service import TavilySearchService

logger = get_logger(__name__)

__all__ = [
    "WebSearchResult",
    "build_web_search_port_from_provider",
    "build_web_search_port_from_yaml",
    "resolve_web_search_port",
]


# ==================== R5：provider 构造器自注册 ====================

def _build_tavily(api_key: str | None, extra: dict[str, Any]) -> TavilySearchService:
    if not api_key:
        raise WebSearchProviderNotConfiguredError("tavily")
    return TavilySearchService(
        TavilySearchConfig(
            api_key=api_key,
            max_results=int(extra.get("max_results", 10)),
            search_depth=str(extra.get("search_depth", "basic")),
            timeout=int(extra.get("timeout", 30)),
        )
    )


def _build_serpapi(api_key: str | None, extra: dict[str, Any]) -> SerpAPISearchService:
    if not api_key:
        raise WebSearchProviderNotConfiguredError("serpapi")
    return SerpAPISearchService(
        SerpApiSearchConfig(
            api_key=api_key,
            max_results=int(extra.get("max_results", 10)),
            timeout=int(extra.get("timeout", 30)),
            engine=str(extra.get("engine", "google")),
        )
    )


def _build_duckduckgo(api_key: str | None, extra: dict[str, Any]) -> DuckDuckGoSearchService:
    # duckduckgo 免费、无需 key（api_key 参数忽略）
    return DuckDuckGoSearchService(
        DuckDuckGoSearchConfig(
            max_results=int(extra.get("max_results", 10)),
            timeout=int(extra.get("timeout", 15)),
        )
    )


# 构造器挂 _FACTORY_NAME；新增 provider = 写一个 _build_xxx + 挂属性，零分支改动
_build_tavily._FACTORY_NAME = "tavily"  # type: ignore[attr-defined]
_build_serpapi._FACTORY_NAME = "serpapi"  # type: ignore[attr-defined]
_build_duckduckgo._FACTORY_NAME = "duckduckgo"  # type: ignore[attr-defined]


def _scan_registry() -> dict[str, Callable]:
    """扫描本模块下划线 _build_* 构造器，按 _FACTORY_NAME 入注册表（ragflow 模式）。"""
    registry: dict[str, Callable] = {}
    for name, obj in inspect.getmembers(__import__(__name__, fromlist=["_x"]), inspect.isfunction):
        if name.startswith("_build_") and hasattr(obj, "_FACTORY_NAME"):
            registry[obj._FACTORY_NAME] = obj
    return registry


PROVIDER_REGISTRY = _scan_registry()


def build_web_search_port_from_provider(
    provider: str,
    api_key: str | None,
    extra_config: dict | None = None,
) -> WebSearchPort:
    """按 provider 名 + 明文 api_key + extra_config 构造 WebSearchPort（唯一实现）。

    - ``duckduckgo`` 忽略 api_key；tavily/serpapi 缺 key 抛错。
    - 未知 provider 抛 WebSearchError。
    - service 不可用（is_available() False）抛 WebSearchError。
    """
    p = (provider or "").lower()
    builder = PROVIDER_REGISTRY.get(p)
    if builder is None:
        raise WebSearchProviderNotConfiguredError(p or "unknown")
    svc = builder(api_key, extra_config or {})
    if not svc.is_available():
        raise WebSearchProviderUnavailableError(p, "服务不可用或未配置")
    return ProviderWebSearchPort(service=svc)


def build_web_search_port_from_yaml() -> WebSearchPort:
    """按 YAML external_search 全局配置择优构造（Tavily 优先 → DuckDuckGo 兜底）。

    替代原 deep_research 版 ``build_web_search_port`` 与 qa 版 ``_build_yaml_fallback_port``
    （两者语义一致：Tavily 配了 api_key 且可用则用，否则 DuckDuckGo）。
    """
    from novamind.setting.yaml_config import get_config

    es_cfg = get_config().external_search
    if es_cfg.tavily.api_key:
        try:
            return build_web_search_port_from_provider(
                "tavily",
                es_cfg.tavily.api_key,
                {
                    "max_results": es_cfg.tavily.max_results,
                    "search_depth": es_cfg.tavily.search_depth,
                    "timeout": es_cfg.tavily.timeout,
                },
            )
        except WebSearchError as e:
            logger.warning("YAML Tavily 构造失败，试 DuckDuckGo 兜底", error=str(e))
    return build_web_search_port_from_provider(
        "duckduckgo",
        None,
        {
            "max_results": es_cfg.duckduckgo.max_results,
            "timeout": es_cfg.duckduckgo.timeout,
        },
    )


async def resolve_web_search_port(
    search_config_port: Any | None,
    user_id: int,
    *,
    search_provider: str | None = None,
) -> WebSearchPort | None:
    """按「用户显式指定 → 用户首选 → YAML 兜底」择优构造，均失败返回 None。

    ``search_config_port`` 为 SearchConfigService（或旧 SearchConfigPort 兼容对象）；
    各级失败均降级（记 warning 不抛），供 agent 装配点与 qa 联网检索共用。
    """
    # 0. 用户显式指定 provider（聊天时选定）
    if search_provider and search_config_port is not None:
        creds = None
        try:
            creds = await search_config_port.get_search_config_by_provider(
                user_id, search_provider
            )
        except Exception as e:
            logger.warning(
                "读取指定 provider 搜索配置失败，回退自动择优",
                provider=search_provider, error=str(e),
            )
        if creds is not None:
            try:
                return build_web_search_port_from_provider(
                    creds.provider, creds.api_key, creds.extra_config
                )
            except WebSearchError as e:
                logger.warning(
                    "指定 provider 构造端口失败，回退自动择优",
                    provider=creds.provider, error=str(e),
                )
        else:
            logger.info(
                "用户未配置指定 provider，回退自动择优",
                provider=search_provider, user_id=user_id,
            )

    # 1. 用户首选（is_primary）
    if search_config_port is not None:
        creds = None
        try:
            creds = await search_config_port.get_primary_search_config(user_id)
        except Exception as e:
            logger.warning("读取用户搜索配置失败，回退 YAML", error=str(e))
        if creds is not None:
            try:
                return build_web_search_port_from_provider(
                    creds.provider, creds.api_key, creds.extra_config
                )
            except WebSearchError as e:
                logger.warning(
                    "用户级搜索配置构造端口失败，回退 YAML",
                    provider=creds.provider, error=str(e),
                )
            except Exception as e:
                logger.warning(
                    "用户级搜索配置构造端口异常，回退 YAML",
                    provider=creds.provider, error=str(e),
                )

    # 2. YAML 全局兜底
    try:
        return build_web_search_port_from_yaml()
    except Exception as e:
        logger.warning("YAML 搜索兜底构造失败，联网搜索不可用", error=str(e))
        return None
