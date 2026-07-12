"""
Agent 模块异常处理器
"""
from fastapi import FastAPI

from novamind.core.middleware.base_exception_handler import register_module_exceptions
from novamind.features.agent.api.exceptions import (
    AgentError,
    AgentNotFoundError,
    SessionNotFoundError,
    McpServerError,
    McpServerNotFoundError,
    McpConnectionError,
    SandboxError,
    SandboxNotAvailableError,
    SandboxTimeoutError,
    SandboxExecutionError,
    UnsupportedLanguageError,
    ToolExecutionError,
    ToolNotFoundError,
    AgentMaxIterationsError,
    MemoryNotFoundError,
)


def setup_agent_exception_handlers(app: FastAPI) -> None:
    """注册 Agent 模块异常处理器"""
    register_module_exceptions(app, status_map={
        AgentNotFoundError: 404,
        SessionNotFoundError: 404,
        McpServerNotFoundError: 404,
        McpConnectionError: 502,
        McpServerError: 500,
        SandboxNotAvailableError: 503,
        SandboxTimeoutError: 408,
        SandboxExecutionError: 500,
        UnsupportedLanguageError: 422,
        SandboxError: 500,
        ToolExecutionError: 500,
        ToolNotFoundError: 404,
        AgentMaxIterationsError: 409,
        MemoryNotFoundError: 404,
        AgentError: 500,
    })
