"""WebSearchPort 宿主适配器（向后兼容重导出）。

``HostWebSearchPort`` / ``as_web_search_port`` / ``build_web_search_port`` 已迁至
``features/deep_research/adapters/web_search_port_adapter.py``（deep_research 拥有搜索
服务实现，故拥有其端口适配器——DDD 正确归属）。本模块重导出以保持批次 3 agent
代码与测试零改动。
"""
from novamind.features.deep_research.adapters.web_search_port_adapter import (  # noqa: F401
    HostWebSearchPort,
    as_web_search_port,
    build_web_search_port,
)

__all__ = ["HostWebSearchPort", "as_web_search_port", "build_web_search_port"]