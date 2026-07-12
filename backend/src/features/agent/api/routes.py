"""
Agent 模块 API 路由
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Path
from fastapi.responses import StreamingResponse

from novamind.features.user.api.auth import get_current_user
from novamind.features.agent.api.dependencies import (
    get_agent_service,
    get_agent_chat_service,
    get_mcp_server_service,
    get_tool_registry,
    get_minio_client_for_presign,
)
from novamind.features.agent.services.agent_service import AgentService
from novamind.features.agent.services.chat_service import AgentChatService
from novamind.features.agent.services.mcp_server_service import McpServerService
from novamind.features.agent.core.tool.registry import ToolRegistry
from novamind.shared.storage.minio_client import enrich_attachments_with_presigned_urls
from novamind.features.agent.schemas.agent_schema import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentDetailResponse,
    AgentListResponse,
    SessionResponse,
    SessionListResponse,
    MessageListResponse,
    AgentChatRequest,
    McpServerCreate,
    McpServerUpdate,
    McpServerResponse,
    ToolProviderResponse,
    ToolFunctionResponse,
    ActionResponse,
    McpToolsRefreshResponse,
    MemoryListResponse,
    MemoryStatsResponse,
)

router = APIRouter()


async def get_current_user_id(current_user: dict = Depends(get_current_user)) -> int:
    """获取当前用户 ID"""
    return current_user["id"]


def _is_admin(current_user: dict) -> bool:
    """从当前用户信息中提取管理员标识"""
    return current_user.get("is_admin", False)


# ==================== Agent 管理 ====================

@router.post(
    "/agents",
    response_model=AgentDetailResponse,
    summary="创建 Agent",
    description="创建一个新的 Agent 助手",
)
async def create_agent(
    data: AgentCreate,
    user_id: int = Depends(get_current_user_id),
    service: AgentService = Depends(get_agent_service),
):
    return await service.create_agent(user_id, data)


@router.get(
    "/agents",
    response_model=AgentListResponse,
    summary="列出 Agent",
    description="获取当前用户创建的所有 Agent 列表",
)
async def list_agents(
    limit: Annotated[int, Query(ge=1, le=100, description="每页数量")] = 20,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
    user_id: int = Depends(get_current_user_id),
    service: AgentService = Depends(get_agent_service),
):
    return await service.list_agents(user_id, limit, offset)


@router.get(
    "/agents/{agent_id}",
    response_model=AgentDetailResponse,
    summary="获取 Agent 详情",
    description="根据 Agent ID 获取详细信息",
)
async def get_agent(
    agent_id: Annotated[int, Path(gt=0, description="Agent ID")],
    user_id: int = Depends(get_current_user_id),
    service: AgentService = Depends(get_agent_service),
):
    return await service.get_agent(user_id, agent_id)

 
@router.put(
    "/agents/{agent_id}",
    response_model=AgentDetailResponse,
    summary="更新 Agent",
    description="更新 Agent 的配置信息",
)
async def update_agent(
    agent_id: Annotated[int, Path(gt=0, description="Agent ID")],
    data: AgentUpdate,
    user_id: int = Depends(get_current_user_id),
    current_user: dict = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    return await service.update_agent(user_id, agent_id, data, is_admin=_is_admin(current_user))


@router.delete(
    "/agents/{agent_id}",
    response_model=ActionResponse,
    summary="删除 Agent",
    description="删除指定的 Agent 及其相关数据",
)
async def delete_agent(
    agent_id: Annotated[int, Path(gt=0, description="Agent ID")],
    user_id: int = Depends(get_current_user_id),
    current_user: dict = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
):
    await service.delete_agent(user_id, agent_id, is_admin=_is_admin(current_user))
    return {"success": True, "message": "Agent 已删除"}


# ==================== Agent 对话 ====================

@router.post(
    "/agents/{agent_id}/chat-stream",
    summary="Agent 对话（SSE 流式）",
    description="与 Agent 进行流式对话，返回 SSE 格式的事件流",
)
async def chat_stream(
    agent_id: Annotated[int, Path(gt=0, description="Agent ID")],
    data: AgentChatRequest,
    user_id: int = Depends(get_current_user_id),
    service: AgentChatService = Depends(get_agent_chat_service),
):
    return StreamingResponse(
        service.chat_stream(
            user_id=user_id,
            agent_id=agent_id,
            content=data.content,
            session_id=data.session_id,
            llm_model=data.llm_model,
            enable_thinking=data.enable_thinking,
            stream=data.stream,
            attachment_ids=data.attachment_ids,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/agents/{agent_id}/sessions",
    response_model=SessionListResponse,
    summary="列出对话",
    description="获取指定 Agent 的所有对话会话列表",
)
async def list_sessions(
    agent_id: Annotated[int, Path(gt=0, description="Agent ID")],
    limit: Annotated[int, Query(ge=1, le=100, description="每页数量")] = 20,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
    user_id: int = Depends(get_current_user_id),
    service: AgentService = Depends(get_agent_service),
):
    return await service.list_sessions(user_id, agent_id, limit, offset)


@router.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    summary="获取对话详情",
    description="根据会话 ID 获取对话详细信息",
)
async def get_session(
    session_id: Annotated[str, Path(min_length=1, description="会话ID")],
    user_id: int = Depends(get_current_user_id),
    service: AgentService = Depends(get_agent_service),
):
    conv = await service.get_session(user_id, session_id)
    return SessionResponse.model_validate(conv)


@router.delete(
    "/sessions/{session_id}",
    response_model=ActionResponse,
    summary="删除对话",
    description="删除指定的对话会话及其所有消息",
)
async def delete_session(
    session_id: Annotated[str, Path(min_length=1, description="会话ID")],
    user_id: int = Depends(get_current_user_id),
    service: AgentService = Depends(get_agent_service),
):
    await service.delete_session(user_id, session_id)
    return {"success": True, "message": "对话已删除"}


@router.get(
    "/sessions/{session_id}/messages",
    response_model=MessageListResponse,
    summary="获取对话消息",
    description="获取指定会话的消息列表，支持分页",
)
async def get_messages(
    session_id: Annotated[str, Path(min_length=1, description="会话ID")],
    limit: Annotated[int, Query(ge=1, le=200, description="每页数量")] = 50,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
    user_id: int = Depends(get_current_user_id),
    service: AgentService = Depends(get_agent_service),
    minio_client=Depends(get_minio_client_for_presign),
):
    result = await service.get_messages(user_id, session_id, limit, offset)
    if minio_client:
        for msg in result.items:
            await enrich_attachments_with_presigned_urls(msg.extra, minio_client)
    return result


# ==================== MCP 服务器管理 ====================

@router.post(
    "/mcp-servers",
    response_model=McpServerResponse,
    summary="添加 MCP 服务器",
    description="添加一个新的 MCP 服务器配置",
)
async def create_mcp_server(
    data: McpServerCreate,
    user_id: int = Depends(get_current_user_id),
    service: McpServerService = Depends(get_mcp_server_service),
):
    return await service.create_server(user_id, data)


@router.get(
    "/mcp-servers",
    response_model=list[McpServerResponse],
    summary="列出 MCP 服务器",
    description="获取当前用户的所有 MCP 服务器配置列表",
)
async def list_mcp_servers(
    user_id: int = Depends(get_current_user_id),
    service: McpServerService = Depends(get_mcp_server_service),
):
    servers = await service.list_servers(user_id)
    return servers


@router.put(
    "/mcp-servers/{server_id}",
    response_model=McpServerResponse,
    summary="更新 MCP 服务器配置",
    description="更新指定 MCP 服务器的配置信息",
)
async def update_mcp_server(
    server_id: Annotated[int, Path(gt=0, description="MCP 服务器 ID")],
    data: McpServerUpdate,
    user_id: int = Depends(get_current_user_id),
    current_user: dict = Depends(get_current_user),
    service: McpServerService = Depends(get_mcp_server_service),
):
    return await service.update_server(user_id, server_id, data, is_admin=_is_admin(current_user))


@router.delete(
    "/mcp-servers/{server_id}",
    response_model=ActionResponse,
    summary="删除 MCP 服务器配置",
    description="删除指定的 MCP 服务器配置",
)
async def delete_mcp_server(
    server_id: Annotated[int, Path(gt=0, description="MCP 服务器 ID")],
    user_id: int = Depends(get_current_user_id),
    current_user: dict = Depends(get_current_user),
    service: McpServerService = Depends(get_mcp_server_service),
):
    await service.delete_server(user_id, server_id, is_admin=_is_admin(current_user))
    return {"success": True, "message": "MCP 服务器已删除"}


@router.post(
    "/mcp-servers/{server_id}/connect",
    response_model=McpServerResponse,
    summary="连接 MCP 服务器",
    description="建立与指定 MCP 服务器的连接",
)
async def connect_mcp_server(
    server_id: Annotated[int, Path(gt=0, description="MCP 服务器 ID")],
    user_id: int = Depends(get_current_user_id),
    current_user: dict = Depends(get_current_user),
    service: McpServerService = Depends(get_mcp_server_service),
):
    return await service.connect_server(user_id, server_id, is_admin=_is_admin(current_user))


@router.post(
    "/mcp-servers/{server_id}/disconnect",
    response_model=McpServerResponse,
    summary="断开 MCP 服务器",
    description="断开与指定 MCP 服务器的连接",
)
async def disconnect_mcp_server(
    server_id: Annotated[int, Path(gt=0, description="MCP 服务器 ID")],
    user_id: int = Depends(get_current_user_id),
    current_user: dict = Depends(get_current_user),
    service: McpServerService = Depends(get_mcp_server_service),
):
    return await service.disconnect_server(user_id, server_id, is_admin=_is_admin(current_user))


@router.post(
    "/mcp-servers/{server_id}/refresh-tools",
    response_model=McpToolsRefreshResponse,
    summary="刷新 MCP 服务器工具列表",
    description="重新获取指定 MCP 服务器提供的工具列表",
)
async def refresh_mcp_tools(
    server_id: Annotated[int, Path(gt=0, description="MCP 服务器 ID")],
    user_id: int = Depends(get_current_user_id),
    current_user: dict = Depends(get_current_user),
    service: McpServerService = Depends(get_mcp_server_service),
):
    tools = await service.refresh_tools(user_id, server_id, is_admin=_is_admin(current_user))
    return {"success": True, "tools": tools}


@router.post(
    "/mcp-servers/test-connection",
    summary="测试 MCP 服务器连接",
    description="测试 MCP 服务器配置是否有效，不保存配置",
)
async def test_mcp_connection(
    data: McpServerCreate,
    user_id: int = Depends(get_current_user_id),
    service: McpServerService = Depends(get_mcp_server_service),
):
    return await service.test_connection(data)


# ==================== 工具管理 ====================

@router.get(
    "/tools",
    response_model=list[ToolProviderResponse],
    summary="列出可用工具",
    description="获取所有已注册的工具提供者及其工具列表",
)
async def list_tools(
    user_id: int = Depends(get_current_user_id),
    registry: ToolRegistry = Depends(get_tool_registry),
):
    tools = registry.list_tools()
    return [
        ToolProviderResponse(
            name=t.name,
            description=t.description,
            tools=[
                ToolFunctionResponse(
                    name=item.get("function", {}).get("name", ""),
                    description=item.get("function", {}).get("description", ""),
                    parameters=item.get("function", {}).get("parameters", {}),
                )
                for item in t.tools
            ],
            system_prompt_fragment=t.system_prompt_fragment,
        )
        for t in tools
    ]


@router.get(
    "/tools/{tool_name}",
    response_model=ToolProviderResponse,
    summary="获取工具详情",
    description="根据工具名称获取工具提供者的详细信息",
)
async def get_tool(
    tool_name: Annotated[str, Path(min_length=1, description="工具名称")],
    user_id: int = Depends(get_current_user_id),
    registry: ToolRegistry = Depends(get_tool_registry),
):
    tool = registry.get_tool(tool_name)
    if not tool:
        from novamind.features.agent.api.exceptions import ToolNotFoundError
        raise ToolNotFoundError(tool_name)

    tools = tool.get_tools()
    return ToolProviderResponse(
        name=tool.name,
        description=tool.description,
        tools=[
            ToolFunctionResponse(
                name=t.get("function", {}).get("name", ""),
                description=t.get("function", {}).get("description", ""),
                parameters=t.get("function", {}).get("parameters", {}),
            )
            for t in tools
        ],
        system_prompt_fragment=tool.get_system_prompt_fragment(),
    )


# ==================== 记忆管理 ====================

@router.get(
    "/agents/{agent_id}/memories",
    response_model=MemoryListResponse,
    summary="列出记忆",
    description="获取指定 Agent 的长期记忆列表，支持按类别过滤和分页",
)
async def list_memories(
    agent_id: Annotated[int, Path(gt=0, description="Agent ID")],
    category: Optional[str] = Query(None, description="按类别过滤"),
    limit: Annotated[int, Query(ge=1, le=100, description="每页数量")] = 20,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
    user_id: int = Depends(get_current_user_id),
    service: AgentService = Depends(get_agent_service),
):
    return await service.list_memories(user_id, agent_id, category, limit, offset)


@router.delete(
    "/agents/{agent_id}/memories/{memory_id}",
    response_model=ActionResponse,
    summary="删除记忆",
    description="删除指定的长期记忆",
)
async def delete_memory(
    agent_id: Annotated[int, Path(gt=0, description="Agent ID")],
    memory_id: Annotated[int, Path(gt=0, description="记忆 ID")],
    user_id: int = Depends(get_current_user_id),
    service: AgentService = Depends(get_agent_service),
):
    await service.delete_memory(user_id, agent_id, memory_id)
    return {"success": True, "message": "记忆已删除"}


@router.get(
    "/agents/{agent_id}/memories/stats",
    response_model=MemoryStatsResponse,
    summary="记忆统计",
    description="获取指定 Agent 的记忆统计信息",
)
async def get_memory_stats(
    agent_id: Annotated[int, Path(gt=0, description="Agent ID")],
    user_id: int = Depends(get_current_user_id),
    service: AgentService = Depends(get_agent_service),
):
    return await service.get_memory_stats(user_id, agent_id)
