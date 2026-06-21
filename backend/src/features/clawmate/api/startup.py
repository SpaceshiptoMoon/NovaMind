"""
ClawMate 模块初始化

在应用启动时：
1. 创建 SessionManager 单例并挂载到 app.state
2. 创建 ClawMate 专用的 ToolRegistry + ToolExecutor + AgentEngine
3. 注册 ClawMate 异常到全局异常处理器
4. 启动空闲 session 定时清理任务
"""

import asyncio

from src.core.middleware.structured_logging import get_logger
from src.features.clawmate.core.session_manager import SessionManager
from src.features.clawmate.core.config import ClawMateConfig

logger = get_logger(__name__)

# 模块级单例引用
_session_manager: SessionManager | None = None


async def init_clawmate_components(app):
    """初始化 ClawMate 组件"""
    global _session_manager

    config = ClawMateConfig.from_yaml()

    if not config.enabled:
        logger.info("ClawMate 模块已禁用")
        return

    # 1. 创建 SessionManager
    _session_manager = SessionManager(
        default_timeout=config.default_timeout,
        max_idle_seconds=config.max_session_idle,
    )

    # 2. 创建 ClawMate 专用工具链
    from src.features.clawmate.core.tools import ALL_TOOLS
    from src.features.agent.core.tool.registry import ToolRegistry
    from src.features.agent.core.tool.executor import ToolExecutor
    from src.features.agent.core.tool.hooks import LoggingHook, ResultTruncationHook
    from src.features.agent.core.engine import AgentEngine
    from src.features.agent.mcp.client import McpClientManager

    tool_registry = ToolRegistry()
    for tool_cls in ALL_TOOLS:
        tool_registry.register(tool_cls())

    hooks = [
        LoggingHook(),
        ResultTruncationHook(max_result_chars=30_000),  # 终端输出可能很大
    ]
    mcp_manager = McpClientManager()  # 空实例，ClawMate 不使用 MCP
    tool_executor = ToolExecutor(tool_registry, mcp_manager, hooks=hooks)
    agent_engine = AgentEngine(tool_executor)

    # 3. 挂载到 app.state
    app.state.clawmate_session_manager = _session_manager
    app.state.clawmate_engine = agent_engine
    app.state.clawmate_tool_registry = tool_registry

    # 4. 启动定时清理任务
    asyncio.create_task(
        _session_manager.start_cleanup_loop(interval=config.cleanup_interval)
    )

    # 5. 注册异常
    _register_exceptions(app)

    logger.info(
        "ClawMate 模块已初始化",
        default_timeout=config.default_timeout,
        max_session_idle=config.max_session_idle,
        cleanup_interval=config.cleanup_interval,
        tools=[t().name for t in ALL_TOOLS],
    )


def _register_exceptions(app):
    """注册 ClawMate 异常到全局处理器"""
    from src.core.middleware.base_exception_handler import register_module_exceptions
    from src.features.clawmate.api.exceptions import (
        ClawMateError,
        SessionNotInitializedError,
        CommandBlockedError,
        SessionInitError,
    )

    register_module_exceptions(app, status_map={
        SessionNotInitializedError: 404,
        CommandBlockedError: 403,
        SessionInitError: 500,
        ClawMateError: 500,
    })
