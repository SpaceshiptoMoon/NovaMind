"""
WebSearchPort 宿主适配器（向后兼容重导出）+ 按数据库默认搜索引擎构造的装配函数。

实际端口实现归属 deep_research/adapters/；本模块额外提供 ``resolve_web_search_port``，
在装配点按数据库用户默认搜索引擎（is_primary）构造 WebSearchPort 注入 AgentChatService。
"""
from __future__ import annotations

from typing import Optional

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.deep_research.adapters.web_search_port_adapter import (  # noqa: F401
    HostWebSearchPort,
    as_web_search_port,
    build_web_search_port,
)
from novamind.shared.search_config_ports import SearchConfigPort

logger = get_logger(__name__)


async def resolve_web_search_port(
    search_config_port: Optional[SearchConfigPort], user_id: int
) -> Optional[HostWebSearchPort]:
    """按数据库用户默认搜索引擎（is_primary）构造 WebSearchPort。

    1. 用户首选配置 → ``SearchConfigPort.get_primary_search_config()``
       → ``engines.build_web_search_port_from_provider()``（按 provider 构造对应客户端）
    2. YAML 全局兜底 → ``build_web_search_port()``（Tavily 优先 → DuckDuckGo）

    首选 provider 的 api_key 缺失/无效时回退 YAML 兜底；均失败返回 None。
    """
    from novamind.engines.search_errors import WebSearchError
    from novamind.engines.search_ports import build_web_search_port_from_provider

    # 1. 用户首选(is_primary)
    if search_config_port is not None:
        try:
            creds = await search_config_port.get_primary_search_config(user_id)
            if creds is not None:
                try:
                    return build_web_search_port_from_provider(
                        creds.provider, creds.api_key, creds.extra_config
                    )
                except WebSearchError as e:
                    logger.warning(
                        "用户首选搜索端口构造失败，回退 YAML 兜底",
                        provider=creds.provider,
                        error=str(e),
                    )
        except Exception as e:
            logger.warning("读取用户首选搜索配置失败，回退 YAML 兜底", error=str(e))

    # 2. YAML 全局兜底（build_web_search_port: Tavily → DuckDuckGo）
    try:
        return build_web_search_port()
    except Exception as e:
        logger.warning("YAML 搜索端口兜底构造失败", error=str(e))
        return None


__all__ = [
    "HostWebSearchPort",
    "as_web_search_port",
    "build_web_search_port",
    "resolve_web_search_port",
]