"""
通用异常处理器

提供可复用的异常处理器基类
消除各模块中的重复代码
"""

import traceback
from typing import Callable, Dict, Any, ClassVar
from fastapi import Request
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.utils.time_utils import now_china

logger = get_logger(__name__)


class BaseAPIError(Exception):
    """
    API 错误基类

    所有业务异常应该继承此类。
    子类可通过 _serializable_attrs 类变量声明需要序列化到响应的额外属性名。
    """

    http_status_code: ClassVar[int] = 500
    _serializable_attrs: ClassVar[tuple[str, ...]] = ()

    def __init__(self, message: str, code: str = "UNKNOWN_ERROR", details: Dict[str, Any] = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，自动包含 _serializable_attrs 中声明的属性"""
        result = {
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        for attr in self._serializable_attrs:
            value = getattr(self, attr, None)
            if value is not None:
                result[attr] = value
        return result


def _build_trace_context(request: Request) -> dict:
    """提取请求公共上下文（供异常处理器和日志使用）"""
    return {
        "endpoint": str(request.url.path),
        "trace_id": getattr(request.state, "trace_id", "no-trace"),
        "stack_trace": traceback.format_exc(),
    }


def create_error_handler(
    default_status_code: int = 500,
    log_message: str = "模块异常",
    is_warning: bool = False,
    include_request_id: bool = False,
) -> Callable:
    """
    创建异常处理器工厂函数

    优先使用异常类声明的 http_status_code，未声明时 fallback 到 default_status_code。
    子类可在 class 级别声明 http_status_code 覆盖默认状态码，无需通过 status_map 注册。

    Args:
        default_status_code: HTTP 状态码（默认 500）
        log_message: 日志消息
        is_warning: 是否使用 warning 级别日志（默认 error）
        include_request_id: 是否在响应中包含请求 ID

    Returns:
        异常处理器函数
    """
    async def handler(request: Request, exc: BaseAPIError):
        """通用异常处理器"""
        trace_id = getattr(request.state, "trace_id", "no-trace")

        # 优先取异常类的 http_status_code，未声明则用默认值
        status_code = getattr(type(exc), "http_status_code", default_status_code)

        # 记录错误日志
        log_func = logger.warning if is_warning else logger.error
        log_func(
            log_message,
            trace_id=trace_id,
            error_code=exc.code,
            error_message=exc.message,
            path=request.url.path,
            method=request.method,
        )

        # 构建响应
        response_content = {
            "error": exc.to_dict(),
            "timestamp": now_china().isoformat(),
        }

        if include_request_id:
            response_content["request_id"] = trace_id

        return JSONResponse(
            status_code=status_code,
            content=response_content,
        )

    return handler


def register_module_exceptions(
    app,
    exception_classes: list = None,
    status_code: int = 500,
    status_map: Dict[type, int] = None,
) -> None:
    """
    批量注册模块异常处理器

    支持两种用法：
    1. status_map: {异常类: HTTP状态码} 精确控制每个异常的响应状态码
    2. exception_classes + status_code: 所有异常共用一个状态码

    Args:
        app: FastAPI 应用实例
        exception_classes: 异常类列表
        status_code: 默认状态码（仅当使用 exception_classes 时生效）
        status_map: 异常类到 HTTP 状态码的映射

    Example:
        register_module_exceptions(
            app,
            status_map={
                UserNotFoundError: 404,
                UserAlreadyExistsError: 409,
                UserError: 400,  # 兜底
            },
        )
    """
    if status_map:
        for exc_class, sc in status_map.items():
            handler = create_error_handler(sc, f"{exc_class.__name__} 异常")
            app.add_exception_handler(exc_class, handler)
    elif exception_classes:
        handler = create_error_handler(status_code, "模块异常")
        for exc_class in exception_classes:
            app.add_exception_handler(exc_class, handler)


# ========== HTTP 状态码映射 ==========

HTTP_STATUS_MAP = {
    # 4xx 客户端错误
    "NOT_FOUND": 404,
    "ALREADY_EXISTS": 409,
    "INVALID_REQUEST": 400,
    "EXPIRED": 410,
    "ACCESS_DENIED": 403,
    "RATE_LIMITED": 429,

    # 5xx 服务器错误
    "INTERNAL_ERROR": 500,
    "SERVICE_UNAVAILABLE": 503,
}

# 后缀 → HTTP 状态码映射
SUFFIX_STATUS_MAP = {
    "_NOT_FOUND": 404,
    "_ALREADY_EXISTS": 409,
    "_ACCESS_DENIED": 403,
    "_EXPIRED": 410,
    "_LIMIT_EXCEEDED": 429,
    "_INVALID": 400,
    "_ERROR": 400,
    "_PROCESSING_ERROR": 400,
    "_SIZE_EXCEEDED": 400,
    "_INVALID_TYPE": 400,
}


def get_status_code_for_error(error_code: str) -> int:
    """
    根据错误代码获取 HTTP 状态码

    支持精确匹配和后缀匹配：
    - 精确匹配：如 "NOT_FOUND" → 404
    - 后缀匹配：如 "KNOWLEDGE_BASE_NOT_FOUND" → 404（以 "_NOT_FOUND" 结尾）

    Args:
        error_code: 错误代码

    Returns:
        HTTP 状态码
    """
    # 1. 精确匹配
    if error_code in HTTP_STATUS_MAP:
        return HTTP_STATUS_MAP[error_code]

    # 2. 后缀匹配：业务异常码通常为 {RESOURCE}_{GENERIC_CODE}
    # 按后缀长度降序排列，确保更具体的后缀优先匹配（如 _PROCESSING_ERROR 优先于 _ERROR）
    for suffix, status_code in sorted(SUFFIX_STATUS_MAP.items(), key=lambda x: -len(x[0])):
        if error_code.endswith(suffix):
            return status_code

    return 500


# ========== 全局异常处理器 ==========

async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    全局未捕获异常处理器

    捕获所有未被特定处理器处理的异常
    支持业务异常（具有 code/message 属性）自动映射状态码
    """
    trace_id = getattr(request.state, "trace_id", "no-trace")

    # 检测业务异常（具有 code 和 message 属性的异常）
    error_code = getattr(exc, "code", None)
    error_message = getattr(exc, "message", None) or str(exc)

    if error_code:
        # 业务异常：根据 code 映射 HTTP 状态码
        status_code = get_status_code_for_error(error_code)

        logger.warning(
            "业务异常",
            trace_id=trace_id,
            error_code=error_code,
            error_message=error_message,
            path=request.url.path,
            method=request.method,
        )

        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": error_code,
                    "message": error_message,
                    "request_id": trace_id,
                },
                "timestamp": now_china().isoformat(),
            },
        )

    # 记录详细错误日志
    logger.error(
        "未捕获的异常",
        trace_id=trace_id,
        error_type=type(exc).__name__,
        error_message=str(exc),
        path=request.url.path,
        method=request.method,
        exc_info=traceback.format_exc(),
    )

    # 生产环境返回通用错误消息
    from novamind.setting.yaml_config import get_config

    config = get_config()
    is_production = config.environment == "production"

    response_content = {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "服务器内部错误" if is_production else str(exc),
            "request_id": trace_id,
        },
        "timestamp": now_china().isoformat(),
    }

    return JSONResponse(
        status_code=500,
        content=response_content,
    )


async def validation_exception_handler(request: Request, exc) -> JSONResponse:
    """
    请求验证异常处理器

    处理 Pydantic 验证错误

    注意：此处理器通过 app.add_exception_handler(RequestValidationError, ...) 注册，
    FastAPI 保证传入的 exc 参数一定是 RequestValidationError 类型。
    """

    trace_id = getattr(request.state, "trace_id", "no-trace")

    # 提取验证错误详情
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })

    logger.warning(
        "请求验证失败",
        trace_id=trace_id,
        errors=errors,
        path=request.url.path,
        method=request.method,
    )

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "请求参数验证失败",
                "details": errors,
                "request_id": trace_id,
            },
            "timestamp": now_china().isoformat(),
        },
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    HTTPException 处理器

    重点记录 FastAPI / Starlette 在进入路由前抛出的 4xx 异常，
    例如 multipart/form-data 解析失败。
    """
    trace_id = getattr(request.state, "trace_id", "no-trace")

    logger.warning(
        "HTTP 异常",
        trace_id=trace_id,
        status_code=exc.status_code,
        detail=exc.detail,
        path=request.url.path,
        method=request.method,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "timestamp": now_china().isoformat(),
        },
    )


async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Starlette HTTPException 处理器

    兼容 multipart/form-data 解析阶段的异常。
    """
    trace_id = getattr(request.state, "trace_id", "no-trace")

    logger.warning(
        "Starlette HTTP 异常",
        trace_id=trace_id,
        status_code=exc.status_code,
        detail=exc.detail,
        path=request.url.path,
        method=request.method,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "timestamp": now_china().isoformat(),
        },
    )


def setup_global_exception_handlers(app) -> None:
    """
    设置全局异常处理器

    Args:
        app: FastAPI 应用实例
    """
    from fastapi.exceptions import RequestValidationError

    # 请求验证异常
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, starlette_http_exception_handler)

    # 全局异常兜底
    app.add_exception_handler(Exception, global_exception_handler)
    logger.info("全局异常处理器已注册")
