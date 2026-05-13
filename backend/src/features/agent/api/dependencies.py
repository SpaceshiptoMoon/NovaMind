"""
Agent 模块依赖注入
"""
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.database import get_db
from src.features.user.services.model_config_service import ModelConfigService
from src.features.agent.services.agent_service import AgentService
from src.features.agent.services.chat_service import AgentChatService
from src.features.agent.services.mcp_server_service import McpServerService
from src.features.agent.tools.registry import ToolRegistry
from src.features.agent.mcp.client import McpClientManager
from src.features.agent.core.executor import ToolExecutor
from src.features.agent.core.engine import AgentEngine
from src.features.agent.core.memory.working import WorkingMemory


def get_tool_registry(request: Request) -> ToolRegistry:
    return request.app.state.agent_tool_registry


def get_mcp_client_manager(request: Request) -> McpClientManager:
    return request.app.state.agent_mcp_manager


def get_agent_engine(request: Request) -> AgentEngine:
    return request.app.state.agent_engine


def get_working_memory(request: Request) -> WorkingMemory:
    return request.app.state.agent_working_memory


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
    agent_service: AgentService = Depends(get_agent_service),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
    agent_engine: AgentEngine = Depends(get_agent_engine),
    working_memory: WorkingMemory = Depends(get_working_memory),
) -> AgentChatService:
    return AgentChatService(
        db=db,
        agent_service=agent_service,
        model_config_service=model_config_service,
        agent_engine=agent_engine,
        working_memory=working_memory,
    )


async def get_mcp_server_service(
    db: AsyncSession = Depends(get_db),
    mcp_client_manager: McpClientManager = Depends(get_mcp_client_manager),
) -> McpServerService:
    return McpServerService(db=db, mcp_client_manager=mcp_client_manager)
