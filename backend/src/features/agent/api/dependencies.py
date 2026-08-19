"""
Agent 模块依赖注入
"""
from typing import Any, Optional

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.auth import get_current_user
from novamind.core.database.database import get_db
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.features.agent.services.agent_service import AgentService
from novamind.features.agent.services.chat_service import AgentChatService
from novamind.features.agent.services.mcp_server_service import McpServerService
from novamind.engines.agent.tool.registry import ToolRegistry
from novamind.engines.agent.mcp.client import McpClientManager
from novamind.engines.agent.agent_engine import AgentEngine
from novamind.engines.agent.memory.todo_store import TodoStore
from novamind.features.agent.repository.memory_search_repository import MemorySearchRepository
from novamind.features.agent.adapters import (
    HostKnowledgeSearchPort,
    HostMemorySearchPort,
    HostMemoryStorePort,
)
from novamind.features.agent.adapters.web_search_adapter import resolve_web_search_port
from novamind.engines.prompt_provider_adapter import as_prompt_provider


def get_tool_registry(request: Request) -> ToolRegistry:
    return request.app.state.agent_tool_registry


def get_mcp_client_manager(request: Request) -> McpClientManager:
    return request.app.state.agent_mcp_manager


def get_agent_engine(request: Request) -> AgentEngine:
    return request.app.state.agent_engine


def get_todo_store(request: Request) -> TodoStore:
    return request.app.state.agent_todo_store


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


async def get_memory_search_repo() -> Optional[MemorySearchRepository]:
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
    return ModelConfigService(db)


async def get_agent_service(
    db: AsyncSession = Depends(get_db),
) -> AgentService:
    return AgentService(db)


async def get_agent_chat_service(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(_current_user_id),
    agent_service: AgentService = Depends(get_agent_service),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
    agent_engine: AgentEngine = Depends(get_agent_engine),
    todo_store: TodoStore = Depends(get_todo_store),
    memory_search_repo: Optional[MemorySearchRepository] = Depends(get_memory_search_repo),
    minio_client: Optional[Any] = None,
) -> AgentChatService:
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
    prompt_provider = as_prompt_provider()

    # web_search_port：按数据库用户默认搜索引擎（is_primary）构造，首选失败回退 YAML 兜底
    from novamind.features.user.adapters.search_config_port_adapter import as_search_config_port
    search_config_port = as_search_config_port(db)
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
        web_search_port=web_search_port,
        prompt_provider=prompt_provider,
    )


async def get_mcp_server_service(
    db: AsyncSession = Depends(get_db),
    mcp_client_manager: McpClientManager = Depends(get_mcp_client_manager),
) -> McpServerService:
    return McpServerService(db=db, mcp_client_manager=mcp_client_manager)
