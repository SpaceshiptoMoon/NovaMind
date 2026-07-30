"""DeepDoc 日志兼容层（批次 6a 起，委托给 ``shared.engine_logging``）。

历史上 deepdoc 模块经此获取 logger，原实现 try-import
``core.middleware.structured_logging`` 回退 stdlib。批次 6a 切断引擎对宿主
``core.middleware`` 的导入边，统一委托 ``shared.engine_logging.get_logger``
（structlog 优先、stdlib 回退），deepdoc 全体模块经此单一入口获取 logger，
无需各自改动。
"""
from __future__ import annotations

from novamind.shared.engine_logging import get_logger

__all__ = ["get_logger"]