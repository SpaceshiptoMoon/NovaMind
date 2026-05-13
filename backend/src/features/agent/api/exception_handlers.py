"""
Agent 模块异常处理器
"""
from fastapi import Request
from fastapi.responses import JSONResponse

from src.features.agent.api.exceptions import AgentError
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

STATUS_MAP = {
    "AGENT_NOT_FOUND": 404,
    "CONVERSATION_NOT_FOUND": 404,
    "SESSION_NOT_FOUND": 404,
    "MCP_SERVER_NOT_FOUND": 404,
    "MCP_CONNECTION_ERROR": 502,
    "TOOL_EXECUTION_ERROR": 500,
    "TOOL_NOT_FOUND": 404,
    "AGENT_MAX_ITERATIONS": 409,
    "SANDBOX_NOT_AVAILABLE": 503,
    "SANDBOX_TIMEOUT": 408,
    "SANDBOX_EXECUTION_ERROR": 500,
    "SANDBOX_UNSUPPORTED_LANGUAGE": 422,
    "SANDBOX_ERROR": 500,
}


def setup_agent_exception_handlers(app):
    """注册 Agent 模块异常处理器"""

    @app.exception_handler(AgentError)
    async def agent_error_handler(request: Request, exc: AgentError):
        status_code = STATUS_MAP.get(exc.code, 500)
        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "code": exc.code,
                "message": exc.message,
            },
        )
