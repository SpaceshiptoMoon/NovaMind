"""Agent API 模块异常处理器注册。"""
from fastapi import FastAPI

from novamind.core.middleware.base_exception_handler import register_module_exceptions
from novamind.features.agent_api.exceptions import (
    AgentApiError,
    ApiKeyLimitExceededError,
    ApiKeyNotFoundError,
    InvalidApiKeyError,
)


def setup_agent_api_exception_handlers(app: FastAPI) -> None:
    """注册 Agent API 模块异常（状态码已由异常类自身 __dict__ 声明，此处兜底注册映射）。"""
    register_module_exceptions(app, status_map={
        InvalidApiKeyError: 401,
        ApiKeyNotFoundError: 404,
        ApiKeyLimitExceededError: 409,
        AgentApiError: 400,
    })
