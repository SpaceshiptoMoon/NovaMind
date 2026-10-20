"""群聊 API 路由：REST CRUD + WS 一响对话。

WS 协议与单聊一致（bearer.<jwt> subprotocol 认证，action=chat 触发），
事件流在单聊事件集上扩展 group.speaker / group.run_done / notice，
content/reasoning/tool_* 事件 data 内带 member_agent_id 字段（向后兼容）。
"""
import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, WebSocket, WebSocketDisconnect
from novamind.core.auth import get_current_user, get_user_status_resolver
from novamind.core.auth.ws_auth import ws_authenticate, ws_extract_token
from novamind.core.database.database import get_db
from novamind.core.ws import run_stream_to_ws, send_event
from novamind.engines.agent.agent_engine import AgentEngine
from novamind.engines.agent.memory.todo_store import TodoStore
from novamind.engines.agent.safety import SteeringQueue
from novamind.features.agent.api.dependencies import (
    build_agent_chat_service,
    get_agent_engine_ws,
    get_agent_service,
    get_memory_search_repo,
    get_model_config_service,
    get_todo_store_ws,
)
from novamind.features.agent.exceptions import AgentError
from novamind.features.agent.models.group import AgentGroupRun
from novamind.features.agent.schemas.agent_schema import MessageListResponse
from novamind.features.agent.schemas.group_schema import (
    AgentGroupCreate,
    AgentGroupDetailResponse,
    AgentGroupListResponse,
    AgentGroupRunResponse,
    AgentGroupUpdate,
)
from novamind.features.agent.services.agent_service import AgentService
from novamind.features.agent.services.group_orchestrator import GroupOrchestrator
from novamind.features.agent.services.group_service import GroupService
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.features.user.services.user_service import UserService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


async def get_group_service(
    db: AsyncSession = Depends(get_db),
) -> GroupService:
    """提供请求级 GroupService。"""
    return GroupService(db)


async def get_current_user_id(current_user: dict = Depends(get_current_user)) -> int:
    """获取当前用户 ID。"""
    return current_user["id"]


# ==================== 群 CRUD ====================


@router.post(
    "/groups",
    response_model=AgentGroupDetailResponse,
    summary="创建群聊",
    description="创建多智能体群聊（brainstorm/consult），成员为既有 Agent（≥2）",
)
async def create_group(
    data: AgentGroupCreate,
    user_id: int = Depends(get_current_user_id),
    service: GroupService = Depends(get_group_service),
):
    return await service.create_group(user_id, data)


@router.get(
    "/groups",
    response_model=AgentGroupListResponse,
    summary="我的群列表",
    description="分页列出当前用户的群聊（created_at 倒序）",
)
async def list_groups(
    user_id: int = Depends(get_current_user_id),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    service: GroupService = Depends(get_group_service),
):
    return await service.list_groups(user_id, limit, offset)


@router.get(
    "/groups/{group_id}",
    response_model=AgentGroupDetailResponse,
    summary="群详情",
    description="取群详情（含成员清单与编排参数）",
)
async def get_group(
    group_id: Annotated[int, Path(gt=0)],
    user_id: int = Depends(get_current_user_id),
    service: GroupService = Depends(get_group_service),
):
    return await service.get_group(user_id, group_id)


@router.put(
    "/groups/{group_id}",
    response_model=AgentGroupDetailResponse,
    summary="更新群",
    description="改群配置/全量替换成员（consult 模式校验主持人∈成员）",
)
async def update_group(
    group_id: Annotated[int, Path(gt=0)],
    data: AgentGroupUpdate,
    user_id: int = Depends(get_current_user_id),
    service: GroupService = Depends(get_group_service),
):
    return await service.update_group(user_id, group_id, data)


@router.delete(
    "/groups/{group_id}",
    summary="解散群",
    description="删除群与成员关联（成员私有会话保留）",
)
async def delete_group(
    group_id: Annotated[int, Path(gt=0)],
    user_id: int = Depends(get_current_user_id),
    service: GroupService = Depends(get_group_service),
):
    await service.delete_group(user_id, group_id)
    return {"success": True, "message": "群已解散"}


# ==================== 群会话 ====================


@router.post(
    "/groups/{group_id}/sessions",
    summary="开群会话",
    description="取/建群会话（时间线载体），返回 session_id",
)
async def create_group_session(
    group_id: Annotated[int, Path(gt=0)],
    user_id: int = Depends(get_current_user_id),
    service: GroupService = Depends(get_group_service),
):
    conv = await service.get_or_create_group_session(user_id, group_id)
    return {"session_id": conv.session_id}


@router.get(
    "/groups/{group_id}/sessions/{session_id}/messages",
    response_model=MessageListResponse,
    summary="群时间线消息",
    description="分页取群会话消息（时间线投影：用户消息+成员公开发言）",
)
async def list_group_messages(
    group_id: Annotated[int, Path(gt=0)],
    session_id: Annotated[str, Path(description="群会话 UUID")],
    user_id: int = Depends(get_current_user_id),
    service: GroupService = Depends(get_group_service),
    agent_service: AgentService = Depends(get_agent_service),
):
    # 校验群会话归属后复用单聊消息分页（时间线即该会话的消息流）
    await service.get_or_create_group_session(user_id, group_id, session_id=session_id)
    return await agent_service.get_messages(user_id, session_id)


@router.get(
    "/groups/{group_id}/runs",
    response_model=list[AgentGroupRunResponse],
    summary="群运行历史",
    description="列出群最近的一响运行记录（started_at 倒序）",
)
async def list_group_runs(
    group_id: Annotated[int, Path(gt=0)],
    user_id: int = Depends(get_current_user_id),
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    db: AsyncSession = Depends(get_db),
    service: GroupService = Depends(get_group_service),
):
    from sqlalchemy import select

    await service.get_group(user_id, group_id)
    stmt = (
        select(AgentGroupRun)
        .where(AgentGroupRun.group_id == group_id, AgentGroupRun.user_id == user_id)
        .order_by(AgentGroupRun.started_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [AgentGroupRunResponse.model_validate(r) for r in result.scalars().all()]


# ==================== 群 WS 对话 ====================


@router.websocket("/groups/{group_id}/ws")
async def group_chat_ws(
    websocket: WebSocket,
    group_id: Annotated[int, Path(gt=0)],
    db: AsyncSession = Depends(get_db),
    resolver: UserService = Depends(get_user_status_resolver),
    agent_service: AgentService = Depends(get_agent_service),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
    agent_engine: AgentEngine = Depends(get_agent_engine_ws),
    todo_store: TodoStore = Depends(get_todo_store_ws),
    memory_search_repo = Depends(get_memory_search_repo),
):
    """群对话（WebSocket 流式）：一响编排事件推送。

    认证与消息协议与单聊一致；服务端推送 session/group.speaker/content/
    reasoning/tool_call/tool_result/notice/group.run_done/error 事件流。
    """
    user, close_code = await ws_authenticate(websocket, resolver)
    token = ws_extract_token(websocket)
    await websocket.accept(subprotocol=f"bearer.{token}" if token else None)
    if close_code is not None:
        await websocket.close(code=close_code)
        return

    try:
        msg = await websocket.receive_json()
    except (WebSocketDisconnect, OSError):
        return

    if not isinstance(msg, dict) or msg.get("action") != "chat":
        await websocket.send_json(
            {"type": "error", "data": {"content": "未知 action，期望 action=chat"}}
        )
        await websocket.close()
        return

    content = str((msg.get("payload") or {}).get("content") or "").strip()
    session_id = (msg.get("payload") or {}).get("session_id")
    if not content:
        await websocket.send_json(
            {"type": "error", "data": {"content": "消息内容不能为空"}}
        )
        await websocket.close()
        return

    from novamind.engines.agent.memory.short_term import sanitize_user_content

    user_id_val = user["id"]
    service = await build_agent_chat_service(
        db, user_id_val, agent_service, model_config_service, agent_engine,
        todo_store, memory_search_repo, None,
    )
    group_service = GroupService(db)
    orchestrator = GroupOrchestrator(db, service)

    send_lock = asyncio.Lock()
    steering_queue = SteeringQueue()

    async def locked_send(event):
        async with send_lock:
            await send_event(websocket, event)

    async def run_pipeline():
        """触发前检查（并发护栏）→ 建 run → 一响编排事件转发。"""
        try:
            group = await group_service.group_repo.get_group(group_id, user_id_val)
            if group is None:
                await locked_send({"type": "error", "data": {"content": f"群 {group_id} 不存在"}})
                return
            conv = await group_service.get_or_create_group_session(
                user_id_val, group_id, session_id
            )
            await group_service.ensure_no_running_run(group.id, conv.session_id)
            # 落用户消息到群时间线（时间线含用户消息，成员侧经投递收到）
            await agent_service.save_message(
                conversation_id=conv.id, role="user",
                content=sanitize_user_content(content),
            )
            run = await group_service.start_run(user_id_val, group, conv.session_id)
            await db.commit()
            gen = orchestrator.run_round(
                group=group, group_session=conv, run=run,
                user_content=content, steering_queue=steering_queue,
            )
            try:
                async for event in gen:
                    await locked_send(event)
            finally:
                # 断连/取消时必须显式关闭生成器：aclose 在挂起点向 run_round 抛
                # GeneratorExit，触发其 except 分支把 run 置 cancelled——否则 run
                # 永远卡 running，并发护栏从此拒绝该群的一切新消息
                await gen.aclose()
        except AgentError as e:
            await locked_send({"type": "error", "data": {"content": e.message}})
        except Exception as e:
            await db.rollback()
            await locked_send({"type": "error", "data": {"content": f"群讨论失败：{e}"}})

    async def recv_client_messages():
        """收运行中插话（action=message → steering 队列）。"""
        while True:
            try:
                m = await websocket.receive_json()
            except (WebSocketDisconnect, OSError):
                break
            if isinstance(m, dict) and m.get("action") == "message":
                steering_queue.put(str(m.get("content") or ""))

    send_task = asyncio.create_task(run_pipeline())
    recv_task = asyncio.create_task(recv_client_messages())
    try:
        await send_task
    finally:
        recv_task.cancel()
