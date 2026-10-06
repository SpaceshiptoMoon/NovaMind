"""Agent API 模块异常处理器注册。

管理端点走统一信封（register_module_exceptions）；OpenAI 网关端点走
OpenAI 错误格式（GatewayError 专属 handler + 按路径分流）。
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from novamind.core.middleware.base_exception_handler import (
    BaseAPIError,
    register_module_exceptions,
)
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent_api.exceptions import (
    AgentApiError,
    ApiKeyLimitExceededError,
    ApiKeyNotFoundError,
    GatewayAuthError,
    InvalidApiKeyError,
)

logger = get_logger(__name__)

# OpenAI 官方错误 type 惯例值（SDK 依赖该字段区分重试策略与错误归类）
OPENAI_TYPE_INVALID_REQUEST = "invalid_request_error"
OPENAI_TYPE_AUTH = "invalid_request_error"
OPENAI_TYPE_RATE_LIMIT = "rate_limit_error"
OPENAI_TYPE_API = "api_error"


def openai_error_body(
    message: str,
    err_type: str,
    code: str | None = None,
    param: str | None = None,
) -> dict:
    """构造 OpenAI 错误信封（官方格式：顶层唯一 error 键，SDK 据此解析）。"""
    return {
        "error": {
            "message": message,
            "type": err_type,
            "param": param,
            "code": code,
        }
    }


def openai_error_response(
    status_code: int,
    message: str,
    err_type: str,
    code: str | None = None,
    param: str | None = None,
) -> JSONResponse:
    """OpenAI 错误 JSONResponse 快捷构造。"""
    return JSONResponse(
        status_code=status_code,
        content=openai_error_body(message, err_type, code, param),
    )


async def gateway_auth_error_handler(request: Request, exc: GatewayAuthError) -> JSONResponse:
    """网关鉴权失败 → 401 OpenAI 格式（SDK 侧归类为认证错误）。"""
    logger.warning(
        "网关鉴权失败",
        error_code=exc.code,
        path=request.url.path,
        method=request.method,
    )
    return openai_error_response(
        401, exc.message, OPENAI_TYPE_AUTH, code="invalid_api_key",
    )


def setup_agent_api_exception_handlers(app: FastAPI) -> None:
    """注册 Agent API 模块异常（状态码已由异常类自身 __dict__ 声明，此处兜底注册映射）。"""
    register_module_exceptions(app, status_map={
        InvalidApiKeyError: 401,
        ApiKeyNotFoundError: 404,
        ApiKeyLimitExceededError: 409,
        AgentApiError: 400,
    })
    # OpenAI 网关：专属鉴权 handler（401 OpenAI 格式）。网关路由内的其余
    # 业务异常不经全局 BaseAPIError 兜底——路由层自行转 OpenAI 错误响应，
    # 避免 /v1/* 对外泄漏统一信封格式。
    app.add_exception_handler(GatewayAuthError, gateway_auth_error_handler)
