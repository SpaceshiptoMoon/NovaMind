"""引擎库日志提供者（批次 6a 新增，批次 6b 迁入 ``novamind-engine-core/logging.py``）。

引擎候选模块经此获取 logger，切断对
``novamind.core.middleware.structured_logging`` 的导入边（抽包前必解的遗留接缝）。

设计：
  - 宿主侧已通过 ``setup_structured_logging`` 全局配置 structlog，故优先返回
    ``structlog.get_logger(name)``——日志在宿主内行为与原先逐字一致
    （JSON 结构化、contextvars 合并、exc_info 渲染、调用位置等均由 structlog 处理）。
  - 嵌入方若未安装 structlog，回退到 stdlib ``logging``（库标准做法：库用 stdlib
    logging，由嵌入方配置 handler）。``StdLogger`` 满足 ``engine_ports.Logger``
    Protocol，调用形态对齐 structlog BoundLogger（``info(event, **kw)``，
    ``**kw`` 作为结构化字段经 stdlib ``extra`` 传递，``exc_info`` 等特殊键透传 stdlib）。

依赖方向：本模块仅依赖 ``engine_ports``（同属中立 shared，批次 6b 同迁 engine-core）
与 stdlib/structlog（第三方库，非宿主业务），零宿主 feature/setting/core 边。
"""
from __future__ import annotations

import logging
from typing import Any

from novamind_engine_core.engine_ports import Logger

__all__ = ["Logger", "StdLogger", "get_logger"]

# stdlib Logger 自身接受的、不应塞入 extra 的关键字参数（exc_info 等透传 stdlib）。
_STDLIB_KW_KEYS = frozenset({"exc_info", "stack_info", "stacklevel"})


class StdLogger:
    """stdlib logging 后端的 Logger 实现，满足 ``engine_ports.Logger`` Protocol。

    调用形态对齐 structlog BoundLogger：``info(event: str, **kw)``，
    其中 ``**kw`` 作为结构化字段经 stdlib ``extra`` 传递；``exc_info`` 等
    stdlib 原生关键字透传给 stdlib（由 stdlib 渲染异常信息）。
    """

    __slots__ = ("_logger",)

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    @staticmethod
    def _split(kwargs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """将调用 kwargs 拆为 stdlib extra（结构化字段）与 stdlib 原生关键字。"""
        extra = {k: v for k, v in kwargs.items() if k not in _STDLIB_KW_KEYS}
        stdlib_kw = {k: v for k, v in kwargs.items() if k in _STDLIB_KW_KEYS}
        return extra, stdlib_kw

    def debug(self, event: Any, *args: Any, **kwargs: Any) -> None:
        extra, stdlib_kw = self._split(kwargs)
        self._logger.debug(event, *args, extra=extra, **stdlib_kw)

    def info(self, event: Any, *args: Any, **kwargs: Any) -> None:
        extra, stdlib_kw = self._split(kwargs)
        self._logger.info(event, *args, extra=extra, **stdlib_kw)

    def warning(self, event: Any, *args: Any, **kwargs: Any) -> None:
        extra, stdlib_kw = self._split(kwargs)
        self._logger.warning(event, *args, extra=extra, **stdlib_kw)

    def error(self, event: Any, *args: Any, **kwargs: Any) -> None:
        extra, stdlib_kw = self._split(kwargs)
        self._logger.error(event, *args, extra=extra, **stdlib_kw)

    def critical(self, event: Any, *args: Any, **kwargs: Any) -> None:
        extra, stdlib_kw = self._split(kwargs)
        self._logger.critical(event, *args, extra=extra, **stdlib_kw)

    def exception(self, event: Any = None, *args: Any, **kwargs: Any) -> None:
        """对齐 structlog ``exception()``：默认 ``exc_info=True``。"""
        extra, stdlib_kw = self._split(kwargs)
        stdlib_kw.setdefault("exc_info", True)
        self._logger.error(event, *args, extra=extra, **stdlib_kw)


try:  # structlog 为宿主依赖，嵌入场景可能缺失
    import structlog  # noqa: F401

    _HAS_STRUCTLOG = True
except ImportError:  # pragma: no cover - 嵌入方未安装 structlog 的回退路径
    _HAS_STRUCTLOG = False


def get_logger(name: str) -> Logger:
    """获取引擎库 logger。

    优先 ``structlog.get_logger(name)``（宿主已全局配置，行为逐字保留）；
    structlog 缺失时回退 ``StdLogger(name)``（stdlib，嵌入标准做法）。
    """
    if _HAS_STRUCTLOG:
        import structlog

        return structlog.get_logger(name)
    return StdLogger(name)