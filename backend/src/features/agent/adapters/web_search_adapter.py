"""
WebSearchPort 宿主适配器（向后兼容重导出），实际实现归属 deep_research/adapters/。
"""
from novamind.features.deep_research.adapters.web_search_port_adapter import (  # noqa: F401
    HostWebSearchPort,
    as_web_search_port,
    build_web_search_port,
)

__all__ = ["HostWebSearchPort", "as_web_search_port", "build_web_search_port"]