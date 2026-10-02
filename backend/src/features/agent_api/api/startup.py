"""agent_api 启动接线：MCP server 挂载与生命周期管理。

session_manager.run() 是 asynccontextmanager，mount 的子 app 不会触发它——
必须由 init_hook 显式进入上下文并把 exit stack 存 app.state，
应用关闭时由 startup_manager._cleanup 调 aclose。
"""
from __future__ import annotations

from contextlib import AsyncExitStack

from fastapi import FastAPI
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


async def init_agent_api_components(app: FastAPI) -> None:
    """装配 MCP server：进入 session_manager 生命周期 + 挂 /mcp ASGI 端点。"""
    from novamind.features.agent_api.mcp.server import MCP_SERVER_NAME, McpAsgiEndpoint, build_mcp_server

    mcp = build_mcp_server()
    # session_manager 懒创建——必须先调 streamable_http_app() 触发初始化
    # （真实环境验证抓到：直接访问 mcp.session_manager 抛
    #   "Session manager can only be accessed after calling streamable_http_app()"）
    mcp.streamable_http_app()
    stack = AsyncExitStack()
    await stack.enter_async_context(mcp.session_manager.run())

    # 只挂显式 Route（不 mount）：McpAsgiEndpoint 是自包含 ASGI 端点，无需
    # mount 的路径剥离；双路径注册消灭尾斜杠 307（无钥请求连重定向都不给）
    import starlette.routing

    endpoint = McpAsgiEndpoint(mcp.session_manager)
    app.router.routes.extend([
        starlette.routing.Route("/mcp", endpoint, methods=["GET", "POST", "DELETE"]),
        starlette.routing.Route("/mcp/", endpoint, methods=["GET", "POST", "DELETE"]),
    ])
    app.state.agent_api_mcp = stack
    logger.info(
        "MCP server 已挂载",
        name=MCP_SERVER_NAME, path="/mcp", transport="streamable_http",
        tools=["kb_search", "kb_ask"],
    )


async def close_agent_api_components(app: FastAPI) -> None:
    """关闭 MCP session_manager（startup_manager._cleanup 调用；异常不外抛）。"""
    stack: AsyncExitStack | None = getattr(app.state, "agent_api_mcp", None)
    if stack is None:
        return
    try:
        await stack.aclose()
        logger.info("MCP server 会话管理器已关闭")
    except Exception as e:
        logger.warning("MCP server 关闭失败（忽略）", error=str(e))
