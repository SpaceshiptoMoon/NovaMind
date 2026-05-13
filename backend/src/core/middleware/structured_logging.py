"""
结构化日志配置模块
按照统一规范配置日志记录，所有日志输出为 JSON 格式
"""
import logging
import sys
from pathlib import Path
import logging.handlers
from typing import Any

import structlog
from structlog.types import EventDict


def setup_structured_logging(service_name: str = "novamind-backend") -> None:
    """
    设置结构化日志配置

    Args:
        service_name: 服务名称，用于日志字段
    """
    # 创建 logs 目录
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    # 配置 structlog
    structlog.configure(
        processors=[
            # 1. 首先合并上下文变量（必须在最前面）
            structlog.contextvars.merge_contextvars,
            # 添加日志级别
            structlog.stdlib.add_log_level,
            # 添加日志记录器名称
            structlog.stdlib.add_logger_name,
            # 添加时间戳（ISO 8601 格式）
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            # 添加调用位置信息
            _add_caller_info,
            # 处理异常信息
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # 将上下文变量合并到日志中
            structlog.processors.CallsiteParameterAdder(
                [
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            # JSON 渲染器（生产环境，ensure_ascii=False 保留中文）
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        # 使用标准库的日志系统
        wrapper_class=structlog.stdlib.BoundLogger,
        # 日志工厂
        logger_factory=structlog.stdlib.LoggerFactory(),
        # 缓存 logger
        cache_logger_on_first_use=True,
    )

    # 配置标准库 logging（用于文件输出）
    _setup_stdlib_logging(logs_dir)


def _setup_stdlib_logging(logs_dir: Path) -> None:
    """配置标准库 logging 用于文件和控制台输出"""
    # 获取 root logger
    root_logger = logging.getLogger()

    # 清除现有的 handlers
    root_logger.handlers.clear()

    root_logger.setLevel(logging.INFO)

    # 创建格式化器（用于文件日志的可读性）
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
    )

    # 控制台处理器（使用 structlog 的 JSON 输出）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    # 文件处理器（使用固定文件名 + 轮转）
    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "app.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 设置第三方库日志级别
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _add_caller_info(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """
    添加调用者信息到日志事件字典

    Args:
        logger: 日志记录器
        method_name: 方法名
        event_dict: 事件字典

    Returns:
        更新后的事件字典
    """
    # 添加服务名称（可以通过配置传入）
    event_dict["service"] = "novamind-backend"

    # 确保 trace_id 存在（从上下文中获取或生成默认值）
    if "trace_id" not in event_dict:
        event_dict["trace_id"] = "no-trace"

    return event_dict


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    获取结构化日志记录器

    Args:
        name: 日志记录器名称（通常使用 __name__）

    Returns:
        结构化日志记录器实例
    """
    return structlog.get_logger(name)


class LoggingMiddleware:
    """
    日志中间件基类，提供辅助方法
    """

    @staticmethod
    def bind_context(**kwargs: Any) -> None:
        """
        绑定上下文变量到当前日志记录器

        Args:
            **kwargs: 要绑定的上下文变量
        """
        structlog.contextvars.bind_contextvars(**kwargs)

    @staticmethod
    def clear_context() -> None:
        """清除当前日志上下文"""
        structlog.contextvars.clear_contextvars()

    @staticmethod
    def unbind_context(*keys: str) -> None:
        """
        解绑指定的上下文变量

        Args:
            *keys: 要解绑的变量名
        """
        structlog.contextvars.unbind_contextvars(*keys)
