"""
Agent 模块启动初始化
"""
from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.agent.agent_engine import AgentEngine
from novamind.engines.agent.loop_detection import LoopDetectionConfig
from novamind.engines.agent.mcp.client import McpClientManager
from novamind.engines.agent.memory.todo_store import TodoStore
from novamind.engines.agent.safety import ApprovalHook
from novamind.engines.agent.tool.executor import ToolExecutor
from novamind.engines.agent.tool.hooks import (
    LoggingHook,
    ResultBudgetHook,
    ToolOutputBudgetHook,
    ToolResultSanitizeHook,
)
from novamind.features.agent.tool.registry_setup import build_tool_registry

logger = get_logger(__name__)


async def init_agent_components(app):
    """初始化 Agent 模块组件"""
    # 1. 初始化代码执行沙箱（如果启用；失败只降级不注册 code_execution 工具）
    sandbox = None
    try:
        from novamind.features.agent.sandbox.config import SandboxConfig
        from novamind.features.agent.sandbox.docker_sandbox import DockerSandbox

        sandbox_config = SandboxConfig.from_yaml()
        if sandbox_config.enabled:
            sandbox = DockerSandbox(sandbox_config)
            await sandbox.start()
            if not sandbox.is_started:
                sandbox = None
                logger.warning("沙箱启动失败，代码执行工具不可用")
    except Exception as e:
        sandbox = None
        logger.warning("代码执行沙箱初始化跳过", error=str(e))

    # 2. 创建 TodoStore，装配内置工具注册表（清单声明见 registry_setup）
    todo_store = TodoStore()
    registry = build_tool_registry(todo_store=todo_store, sandbox=sandbox)
    logger.info("内置工具已注册", tools=registry.list_tool_names())

    # 3. 创建 MCP 客户端管理器
    mcp_manager = McpClientManager()

    # 4. 创建工具执行器（含 Hook 链）+ Agent 引擎
    # 消毒钩子在截断/预算钩子之前：SSE 预览与 metadata 基于消毒后内容生成
    hooks = [
        LoggingHook(),
        ApprovalHook(),
        ToolResultSanitizeHook(),
        ToolOutputBudgetHook(max_tokens=10_000),
        ResultBudgetHook(preview_threshold=10_000, preview_chars=1_500),
    ]
    tool_executor = ToolExecutor(registry, mcp_manager, hooks=hooks)
    engine = AgentEngine(tool_executor, loop_detection=LoopDetectionConfig())

    # 5. 存储到 app.state
    app.state.agent_tool_registry = registry
    app.state.agent_mcp_manager = mcp_manager
    app.state.agent_engine = engine
    app.state.agent_todo_store = todo_store
    if sandbox:
        app.state.agent_sandbox = sandbox

    # 本地工作区 runner 连接注册表（伴生 runner 出站连接的中枢）
    from novamind.features.agent.services.local_workspace.runner_registry import RunnerRegistry

    app.state.runner_registry = RunnerRegistry()

    # 6. 注册异常处理器
    from novamind.features.agent.api.exception_handlers import setup_agent_exception_handlers
    setup_agent_exception_handlers(app)

    # 7. 异步连接系统级 MCP 服务器（如果有）
    try:
        from novamind.core.database.database import get_db_session
        from novamind.engines.agent.mcp.config import McpConnectionConfig
        from novamind.features.agent.repository.agent_repository import McpServerRepository

        async with get_db_session() as db:
            repo = McpServerRepository(db)
            system_servers = await repo.list_enabled_system_servers()
            for server in system_servers:
                try:
                    config = McpConnectionConfig.from_db_config(
                        server.transport_type, server.connection_config
                    )
                    await mcp_manager.connect_server(server.id, server.name, config)
                    await repo.update(server.id, status="connected")
                    logger.info("系统级 MCP 服务器已连接", server_name=server.name)
                except Exception as e:
                    await repo.update(server.id, status="error", last_error=str(e))
                    logger.warning(
                        "系统级 MCP 服务器连接失败",
                        server_name=server.name,
                        error=str(e),
                    )
    except Exception as e:
        logger.warning("系统级 MCP 服务器初始化跳过", error=str(e))

    # 8. 注册应用关闭事件，清理沙箱容器
    if sandbox:
        async def _cleanup_sandbox():
            try:
                await sandbox.cleanup()
                logger.info("沙箱容器已清理")
            except Exception as e:
                logger.warning("清理沙箱容器失败", error=str(e))

        app.add_event_handler("shutdown", _cleanup_sandbox)

    logger.info("Agent 模块初始化完成")
