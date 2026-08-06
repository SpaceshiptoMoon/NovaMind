"""
shared 公共日志门面，提供 Logger 协议、StdLogger stdlib 后端及 get_logger 工厂函数。
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

__all__ = ["Logger", "StdLogger", "get_logger"]


@runtime_checkable
class Logger(Protocol):
    """结构化日志协议，对齐 structlog BoundLogger 的调用形态。

    引擎内模块级不再直接 `get_logger(...)`，而是在构造器接收一个 Logger 实例。
    宿主侧把 `structured_logging.get_logger(name)` 返回的 BoundLogger 直接注入
    （structlog BoundLogger 满足该 Protocol 的方法签名，duck-type 兼容）。

    注意：structlog 的方法是 `info(event: str, **kw)`，而非 stdlib 的
    `info("msg %s", arg)`，本协议与之对齐。
    """

    def debug(self, event: str, **kwargs: Any) -> None: ...

    def info(self, event: str, **kwargs: Any) -> None: ...

    def warning(self, event: str, **kwargs: Any) -> None: ...

    def error(self, event: str, **kwargs: Any) -> None: ...


# stdlib Logger 自身接受的、不应塞入 extra 的关键字参数（exc_info 等透传 stdlib）。
_STDLIB_KW_KEYS = frozenset({"exc_info", "stack_info", "stacklevel"})


class StdLogger:
    """stdlib logging 后端的 Logger 实现，满足 ``Logger`` Protocol。

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
    """获取 logger。

    优先 ``structlog.get_logger(name)``（宿主已全局配置，行为逐字保留）；
    structlog 缺失时回退 ``StdLogger(name)``（stdlib，嵌入标准做法）。
    """
    if _HAS_STRUCTLOG:
        import structlog

        return structlog.get_logger(name)
    return StdLogger(name)