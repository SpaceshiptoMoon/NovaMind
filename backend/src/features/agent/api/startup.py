"""
Agent 模块启动初始化
"""
from src.core.middleware.structured_logging import get_logger
from src.features.agent.tools.registry import ToolRegistry
from src.features.agent.tools.builtins import KnowledgeSearchTool, WebSearchTool, CodeExecutionTool
from src.features.agent.mcp.client import McpClientManager
from src.features.agent.core.executor import ToolExecutor
from src.features.agent.core.engine import AgentEngine
from src.features.agent.core.memory.working import WorkingMemory

logger = get_logger(__name__)


async def init_agent_components(app):
    """初始化 Agent 模块组件"""
    # 1. 创建工具注册表并注册内置工具
    registry = ToolRegistry()
    registry.register(KnowledgeSearchTool())
    registry.register(WebSearchTool())

    # 2. 初始化代码执行沙箱（如果启用）
    sandbox = None
    try:
        from src.features.agent.sandbox.config import SandboxConfig
        from src.features.agent.sandbox.docker_sandbox import DockerSandbox

        sandbox_config = SandboxConfig.from_yaml()
        if sandbox_config.enabled:
            sandbox = DockerSandbox(sandbox_config)
            await sandbox.start()
            if sandbox.is_started:
                registry.register(CodeExecutionTool(sandbox))
                logger.info("代码执行工具已注册")
            else:
                logger.warning("沙箱启动失败，代码执行工具不可用")
    except Exception as e:
        logger.warning("代码执行沙箱初始化跳过", error=str(e))

    logger.info("内置工具已注册", tools=registry.list_tool_names())

    # 3. 创建 MCP 客户端管理器
    mcp_manager = McpClientManager()

    # 4. 创建工具执行器和 Agent 引擎
    tool_executor = ToolExecutor(registry, mcp_manager)
    working_memory = WorkingMemory(default_ttl=3600)
    engine = AgentEngine(tool_executor)

    # 5. 存储到 app.state
    app.state.agent_tool_registry = registry
    app.state.agent_mcp_manager = mcp_manager
    app.state.agent_engine = engine
    app.state.agent_working_memory = working_memory
    if sandbox:
        app.state.agent_sandbox = sandbox

    # 6. 注册异常处理器
    from src.features.agent.api.exception_handlers import setup_agent_exception_handlers
    setup_agent_exception_handlers(app)

    # 7. 异步连接系统级 MCP 服务器（如果有）
    try:
        from src.core.database.database import get_db_session
        from src.features.agent.repository.agent_repository import McpServerRepository
        from src.features.agent.mcp.config import McpConnectionConfig

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
