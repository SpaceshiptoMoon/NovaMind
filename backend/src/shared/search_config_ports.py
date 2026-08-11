"""搜索配置端口 SearchConfigPort 与搜索凭证数据类。

对齐 ``shared/model_config_ports.py`` 先例：feature 间公共端口留 ``shared`` 中立位置。
``SearchConfigService``（features/user）结构化满足本端口；``AIChatService``（features/qa）
经依赖注入按用户级配置择优 provider，不直接 import features/user，避免 feature 间硬耦合。

``shared`` 层不依赖 features/engines/setting；``SearchCredentials`` 仅承载纯数据
（provider/api_key 明文/extra_config），由装配点交给 ``engines.search_ports`` 构造端口。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@dataclass
class SearchCredentials:
    """搜索凭证（用于构造 ``WebSearchPort``）。

    ``api_key`` 为解密后的明文（供 ``engines.build_web_search_port_from_provider`` 使用）；
    duckduckgo 可为 ``None``。
    """

    provider: str
    api_key: Optional[str] = None
    extra_config: Optional[Dict[str, Any]] = None


@runtime_checkable
class SearchConfigPort(Protocol):
    """搜索配置端口：按用户取首选搜索凭证（``SearchConfigService`` 结构化满足）。

    供 AIChatService 等消费方经依赖注入按用户级配置择优 provider，避免直接 import
    features/user 服务。
    """

    async def get_primary_search_config(self, user_id: int) -> Optional[SearchCredentials]:
        """获取用户首选搜索配置（``is_primary=True`` 那条），无则返回 ``None``。

        返回的 ``api_key`` 为解密后明文，供宿主构造 ``WebSearchPort``。
        """
        ...


__all__ = ["SearchConfigPort", "SearchCredentials"]