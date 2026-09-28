"""
Agent 模块依赖注入
"""
from typing import Any

from fastapi import Depends, Request, WebSocket
from novamind.core.auth import get_current_user
from novamind.core.database.database import get_db
from novamind.engines.agent.agent_engine import AgentEngine
from novamind.engines.agent.mcp.client import McpClientManager
from novamind.engines.agent.memory.todo_store import TodoStore
from novamind.engines.agent.tool.registry import ToolRegistry
from novamind.features.agent.repository.memory_search_repository import MemorySearchRepository
from novamind.features.agent.services.agent_service import AgentService
from novamind.features.agent.services.chat_service import AgentChatService
from novamind.features.agent.services.host_knowledge_search import (
    HostKnowledgeSearchPort,
)
from novamind.features.agent.services.host_memory_store import (
    HostMemorySearchPort,
    HostMemoryStorePort,
)
from novamind.features.agent.services.mcp_server_service import McpServerService
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.prompts.prompt_manager import PromptManager
from novamind.shared.search.web_search_factory import resolve_web_search_port
from sqlalchemy.ext.asyncio import AsyncSession


def get_tool_registry(request: Request) -> ToolRegistry:
    """提供应用级单例工具注册表（app.state.agent_tool_registry）。"""
    return request.app.state.agent_tool_registry


def get_mcp_client_manager(request: Request) -> McpClientManager:
    """提供应用级单例 MCP 客户端管理器（app.state.agent_mcp_manager）。"""
    return request.app.state.agent_mcp_manager


def get_agent_engine(request: Request) -> AgentEngine:
    """提供应用级单例 Agent 引擎（app.state.agent_engine）。"""
    return request.app.state.agent_engine


def get_todo_store(request: Request) -> TodoStore:
    """提供应用级单例 todo 存储（app.state.agent_todo_store）。"""
    return request.app.state.agent_todo_store


# WebSocket 版：WS 端点无法注入 HTTP Request，改从 websocket.app.state 取。
# FastAPI WS 依赖会注入 websocket: WebSocket 参数（类比 HTTP 的 request: Request）。
def get_agent_engine_ws(websocket: WebSocket) -> AgentEngine:
    """WebSocket 版引擎获取：从 websocket.app.state 取应用级单例（WS 端点无法注入 HTTP Request）。"""
    return websocket.app.state.agent_engine


def get_todo_store_ws(websocket: WebSocket) -> TodoStore:
    """WebSocket 版 todo 存储获取：从 websocket.app.state 取应用级单例。"""
    return websocket.app.state.agent_todo_store


async def get_minio_client_for_presign():
    """获取 MinIO 客户端（路由层附件预签名用）"""
    try:
        from novamind.shared.storage.client_factory import ClientFactory
        return await ClientFactory.get_minio_client()
    except Exception:
        return None


async def _current_user_id(current_user: dict = Depends(get_current_user)) -> int:
    """获取当前用户 ID（供装配点按数据库默认搜索引擎构造 WebSearchPort）。"""
    return current_user["id"]


async def get_memory_search_repo() -> MemorySearchRepository | None:
    """获取 ES 记忆检索仓储（可选，ES 不可用时返回 None）"""
    try:
        from novamind.shared.storage.client_factory import ClientFactory

        es_client_wrapper = await ClientFactory.get_elasticsearch_client()
        return MemorySearchRepository(es_client=es_client_wrapper.es_client)
    except Exception:
        return None


async def get_model_config_service(
    db: AsyncSession = Depends(get_db),
) -> ModelConfigService:
    """提供请求级 ModelConfigService（绑定当前请求的 db 会话）。"""
    return ModelConfigService(db)


async def get_agent_service(
    db: AsyncSession = Depends(get_db),
) -> AgentService:
    """提供请求级 AgentService（绑定当前请求的 db 会话）。"""
    return AgentService(db)


async def build_agent_chat_service(
    db: AsyncSession,
    user_id: int,
    agent_service: AgentService,
    model_config_service: ModelConfigService,
    agent_engine: AgentEngine,
    todo_store: TodoStore,
    memory_search_repo: MemorySearchRepository | None,
    minio_client: Any | None,
) -> AgentChatService:
    """构造 AgentChatService（HTTP/WS 装配共用）。

    web_search_port 按数据库用户默认搜索引擎（is_primary）构造；user_id 由调用方
    传入（HTTP 来自 ``_current_user_id``，WS 来自 ``ws_authenticate``）。
    """
    # 延迟获取 MinIO 客户端
    if minio_client is None:
        try:
            from novamind.shared.storage.client_factory import ClientFactory
            minio_client = await ClientFactory.get_minio_client()
        except Exception:
            pass

    # 装配点（批次 5-B3）：5 个引擎端口在此构造后注入，AgentChatService 不再内部构造
    memory_store_port = HostMemoryStorePort(db)
    memory_search_port = (
        HostMemorySearchPort(repo=memory_search_repo) if memory_search_repo else None
    )
    knowledge_search_port = HostKnowledgeSearchPort(db, model_config_service)
    from novamind.features.qa.services.attachment_text_reader import AttachmentTextReader
    attachment_read_port = AttachmentTextReader(db)
    prompt_provider = PromptManager()

    # web_search_port：按数据库用户默认搜索引擎（is_primary）构造，首选失败回退 YAML 兜底
    from novamind.features.user.services.search_config_service import SearchConfigService
    search_config_port = SearchConfigService(db)
    web_search_port = await resolve_web_search_port(search_config_port, user_id)

    return AgentChatService(
        db=db,
        agent_service=agent_service,
        model_config_service=model_config_service,
        agent_engine=agent_engine,
        todo_store=todo_store,
        memory_search_repo=memory_search_repo,
        minio_client=minio_client,
        memory_store_port=memory_store_port,
        memory_search_port=memory_search_port,
        knowledge_search_port=knowledge_search_port,
        attachment_read_port=attachment_read_port,
        web_search_port=web_search_port,
        prompt_provider=prompt_provider,
    )


async def get_agent_chat_service(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(_current_user_id),
    agent_service: AgentService = Depends(get_agent_service),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
    agent_engine: AgentEngine = Depends(get_agent_engine),
    todo_store: TodoStore = Depends(get_todo_store),
    memory_search_repo: MemorySearchRepository | None = Depends(get_memory_search_repo),
    minio_client: Any | None = None,
) -> AgentChatService:
    """装配请求级 AgentChatService（引擎端口在此构造后注入，user_id 取自当前认证用户）。

    Args:
        db: 请求级数据库会话。
        user_id: 当前认证用户 ID（经 _current_user_id 依赖解析）。
        agent_service: 请求级 AgentService。
        model_config_service: 请求级模型配置服务。
        agent_engine: 应用级单例 Agent 引擎。
        todo_store: 应用级单例 todo 存储。
        memory_search_repo: ES 记忆检索仓储；None 表示 ES 不可用，对应端口置空。
        minio_client: MinIO 客户端；None 时内部懒取，取不到则以 None 下发。

    Returns:
        装配完成的 AgentChatService。
    """
    return await build_agent_chat_service(
        db, user_id, agent_service, model_config_service, agent_engine,
        todo_store, memory_search_repo, minio_client,
    )


async def get_mcp_server_service(
    db: AsyncSession = Depends(get_db),
    mcp_client_manager: McpClientManager = Depends(get_mcp_client_manager),
) -> McpServerService:
    """提供请求级 McpServerService（绑定 db 会话与应用级 MCP 客户端管理器）。

    Args:
        db: 请求级数据库会话。
        mcp_client_manager: 应用级单例 MCP 客户端管理器。

    Returns:
        McpServerService 实例。
    """
    return McpServerService(db=db, mcp_client_manager=mcp_client_manager)
