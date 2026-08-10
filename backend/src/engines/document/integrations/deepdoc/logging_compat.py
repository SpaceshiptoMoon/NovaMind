"""
DeepDoc 日志兼容层，统一委托 shared.logging.get_logger。
"""
from __future__ import annotations

from novamind.shared.logging import get_logger

__all__ = ["get_logger"]