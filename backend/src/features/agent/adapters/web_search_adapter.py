"""agent web_search 工具装配（批次 2.1 收敛后为共享工厂的薄转发）。

原按数据库用户默认搜索引擎构造端口的逻辑已收敛到
``shared/search/web_search_factory.resolve_web_search_port``，
本模块保留 import 兼容面。
"""
from __future__ import annotations

from novamind.shared.search.web_search_factory import (  # noqa: F401
    build_web_search_port_from_yaml,
    resolve_web_search_port,
)

__all__ = [
    "build_web_search_port_from_yaml",
    "resolve_web_search_port",
]
