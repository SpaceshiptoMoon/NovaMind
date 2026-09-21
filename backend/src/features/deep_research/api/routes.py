"""
深度研究 API 路由
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, WebSocket, WebSocketDisconnect
from novamind.core.auth import get_current_user, get_user_status_resolver
from novamind.core.auth.ws_auth import ws_authenticate, ws_extract_token
from novamind.core.database.database import get_db
from novamind.core.middleware.structured_logging import get_logger
from novamind.core.ws import run_stream_to_ws, send_event
from novamind.features.deep_research.api.dependencies import get_deep_research_service
from novamind.features.deep_research.models.research_session import (
    ResearchStatus as ModelResearchStatus,
)
from novamind.features.deep_research.schemas.research_schema import (
    ExternalSearchProvider,
    ResearchListItem,
    ResearchListResponse,
    ResearchMode,
    ResearchRequest,
    ResearchResponse,
    ResearchStatus,
    SearchSource,
    SearchSourceInfo,
    SearchSourceListResponse,
)
from novamind.features.deep_research.services.deep_research_service import (
    DeepResearchService,
    parse_plan_json,
    plan_to_event_data,
)
from novamind.features.deep_research.services.plan_feedback_registry import (
    PlanFeedbackRegistry,
)
from novamind.features.deep_research.services.source_registry import source_registry
from novamind.features.knowledge_space.api.dependencies import validate_space_access
from novamind.features.knowledge_space.exceptions import SpaceAccessDeniedError, SpaceNotFoundError
from novamind.features.user.services.user_service import UserService
from novamind.features.user.schemas.user_schema import UserMessageResponse
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
logger = get_logger(__name__)


# ==================== 状态映射 ====================

# Schema 字符串枚举 <-> 模型整数枚举 的双向映射
_STATUS_TO_MODEL = {
    ResearchStatus.PENDING: ModelResearchStatus.PENDING,
    ResearchStatus.RUNNING: ModelResearchStatus.RUNNING,
    ResearchStatus.COMPLETED: ModelResearchStatus.COMPLETED,
    ResearchStatus.FAILED: ModelResearchStatus.FAILED,
    ResearchStatus.CANCELLED: ModelResearchStatus.CANCELLED,
}

_STATUS_TO_SCHEMA = {v: k for k, v in _STATUS_TO_MODEL.items()}


def _map_status_to_model(status: ResearchStatus | None) -> ModelResearchStatus | None:
    """映射 Schema 状态到 Model 状态"""
    if status is None:
        return None
    return _STATUS_TO_MODEL.get(status)


def _map_status_to_schema(status: ModelResearchStatus) -> ResearchStatus:
    """映射 Model 状态到 Schema 状态"""
    return _STATUS_TO_SCHEMA.get(status, ResearchStatus.PENDING)


# ==================== 辅助函数 ====================

def _get_research_topic(research) -> str | None:
    """从 research 的 config 中获取研究主题"""
    config = research.config or {}
    return config.get("research_topic")


def _get_research_tasks(research) -> list | None:
    """从 research 的 plan 中获取研究任务（旧形状兼容：v2 steps 派生 / v1 tasks 原样）"""
    plan = research.plan or {}
    if plan.get("version") == 2:
        return [
            {
                "task_id": s.get("step_id", f"step_{i + 1}"),
                "description": s.get("description", ""),
                "priority": i + 1,
            }
            for i, s in enumerate(plan.get("steps") or [])
            if isinstance(s, dict)
        ]
    return plan.get("tasks")


def _get_research_plan(research) -> dict | None:
    """从 research 的 plan 中获取 v2 结构化计划（旧形状返回 None）。"""
    plan = research.plan or {}
    if plan.get("version") != 2:
        return None
    parsed = parse_plan_json(plan)
    if parsed is None:
        return None
    return plan_to_event_data(parsed)


def _get_final_report(research) -> str | None:
    """从 research 的 result 中获取最终报告"""
    result = research.result or {}
    return result.get("answer")


def _get_search_summary(research) -> dict | None:
    """从 research 的 result 中获取搜索摘要（含全量引用 citations）"""
    result = research.result or {}
    if result:
        return {
            "search_results": result.get("search_results", []),
            "sources": result.get("sources", []),
            "citations": result.get("citations", []),
        }
    return None


# ==================== API 路由 ====================

@router.get(
    "/sources",
    response_model=SearchSourceListResponse,
    summary="获取已注册数据源列表",
    description="返回数据源注册表中的全部数据源（type + 展示名），供前端动态渲染源选项。新数据源注册工厂后自动出现在此列表，前端零改动。",
)
async def list_search_sources(
    validated: tuple = Depends(validate_space_access),
    current_user: dict = Depends(get_current_user),
):
    """获取已注册数据源列表（源发现接口）。

    挂在空间前缀下并复用 ``validate_space_access``：源注册表虽是全局的，
    但源发现需登录 + 空间成员资格，防未授权枚举部署能力。
    """
    space, _member = validated
    sources = [
        SearchSourceInfo(source_type=st, display_name=source_registry.display_name(st))
        for st in source_registry.known_types()
    ]
    return SearchSourceListResponse(sources=sources)


@router.post(
    "",
    response_model=ResearchResponse,
    summary="执行深度研究（非流式）",
    description="基于知识空间执行深度研究，返回完整报告",
)
async def execute_research(
    request: ResearchRequest,
    validated: tuple = Depends(validate_space_access),
    research_service: DeepResearchService = Depends(get_deep_research_service),
    current_user: dict = Depends(get_current_user),
):
    """
    执行深度研究（非流式）

    space_id 为路径参数，由 URL 提供（如 /api/v1/spaces/1/deep-research）。

    请求体示例：
    ```json
    {
        "query": "什么是 RAG 技术？有哪些最佳实践？",
        "research_mode": "standard",
        "search_source": "hybrid",
        "internal_search": {
            "kb_ids": [1, 2],
            "search_mode": SearchMode.CONTENT_HYBRID.value,
            "top_k": 10,
            "vector_weight": 0.7,
            "rerank_enabled": true,
            "rerank_top_k": 5
        },
        "external_search": {
            "provider": "duckduckgo",
            "max_results": 10
        },
        "llm": {
            "llm_model": "gpt-4o",
            "temperature": 0.7,
            "max_tokens": 4096
        }
    }
    ```
    """
    space, member = validated
    space_id = space.id
    user_id = current_user["id"]

    result = await research_service.research(
        space_id=space_id,
        user_id=user_id,
        request=request,
    )

    # 从研究结果获取 external_provider，避免与 service 层重复提取
    external_provider = result.get("external_provider")

    return ResearchResponse(
        session_id=result["session_id"],
        query=result["query"],
        research_mode=result.get("research_mode", request.research_mode),
        search_source=result.get("search_source", request.search_source),
        external_provider=external_provider,
        status=_map_status_to_schema(ModelResearchStatus(result["status"])),
        research_topic=result.get("research_topic"),
        research_tasks=result.get("research_tasks"),
        final_report=result.get("final_report"),
        search_summary=result.get("search_summary"),
        stats=result.get("stats", {}),
        created_at=result.get("created_at"),
        completed_at=result.get("completed_at"),
    )


@router.websocket("/ws")
async def research_ws(
    websocket: WebSocket,
    space_id: Annotated[int, Path(gt=0, description="知识空间 ID")],
    db: AsyncSession = Depends(get_db),
    resolver: UserService = Depends(get_user_status_resolver),
    research_service: DeepResearchService = Depends(get_deep_research_service),
):
    """深度研究（WebSocket 流式，支持计划确认双向交互）。

    路由前缀 ``/api/v1/spaces/{space_id}/deep-research`` + ``/ws`` →
    ``/api/v1/spaces/{space_id}/deep-research/ws``。

    认证：subprotocol ``bearer.<jwt>``（ws_authenticate 校验，失败 close 4401/4403）。
    空间权限：ws_authenticate 拿到 user 后，用 ``space_id`` + ``user["id"]`` 复用
    ``validate_space_access`` 校验空间访问权限（失败 close 4403，握手前 close 由
    Starlette 回 403）。客户端连接后发 ``{"action": "research", "payload": ResearchRequest}``，
    服务端推送 ``{"type": ..., "data": ...}`` 事件流（progress/plan_generated/content/
    done/error）。``auto_accepted_plan=false`` 时计划生成后服务端挂起，客户端发
    ``{"action": "plan_feedback", "decision": "accepted"|"edit_plan", "feedback": "..."}"
    继续（edit_plan 携 feedback 重规划；超时自动接受）。客户端 close 触发 service
    ``asyncio.CancelledError`` → 研究记录标记 CANCELLED。
    """
    user, close_code = await ws_authenticate(websocket, resolver)
    token = ws_extract_token(websocket)
    await websocket.accept(subprotocol=f"bearer.{token}" if token else None)
    if close_code is not None:
        await websocket.close(code=close_code)
        return

    # 空间权限校验（WS 不能用 HTTP Depends(get_current_user_id)，直接传 user_id + db）
    try:
        await validate_space_access(space_id, user_id=user["id"], db=db)
    except (SpaceNotFoundError, SpaceAccessDeniedError):
        await websocket.close(code=4403, reason="无权访问该知识空间")
        return

    try:
        msg = await websocket.receive_json()
    except WebSocketDisconnect:
        return

    if not isinstance(msg, dict) or msg.get("action") != "research":
        await websocket.send_json(
            {"type": "error", "data": {"message": "未知 action，期望 action=research"}}
        )
        await websocket.close()
        return

    try:
        data = ResearchRequest(**(msg.get("payload") or {}))
    except Exception as e:
        await websocket.send_json(
            {"type": "error", "data": {"message": f"请求参数错误：{str(e)}"}}
        )
        await websocket.close()
        return

    # 计划确认双向通道：locked_send（并发 send 加锁）+ send/recv 双 task
    # （deer-flow human_feedback 对齐；参照 agent ApprovalRegistry 先例）
    registry = PlanFeedbackRegistry()
    send_lock = asyncio.Lock()

    async def locked_send(event):
        async with send_lock:
            await send_event(websocket, event)

    gen = research_service.research_stream(
        space_id=space_id,
        user_id=user["id"],
        request=data,
        feedback_registry=registry,
    )

    async def recv_plan_feedback():
        """并发收用户 WS 消息（计划反馈 → registry.resolve）。"""
        while True:
            try:
                msg = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            if (
                isinstance(msg, dict)
                and msg.get("action") == "plan_feedback"
            ):
                registry.resolve(
                    str(msg.get("decision", "accepted")),
                    str(msg.get("feedback", "") or ""),
                )

    send_task = asyncio.create_task(
        run_stream_to_ws(websocket, gen, send_fn=locked_send)
    )
    recv_task = asyncio.create_task(recv_plan_feedback())
    try:
        await send_task
    finally:
        recv_task.cancel()


@router.get(
    "",
    response_model=ResearchListResponse,
    summary="获取研究历史列表",
    description="获取知识空间的研究历史记录列表，普通用户只能查看自己的研究，管理员可查看所有研究",
)
async def list_researches(
    validated: tuple = Depends(validate_space_access),
    research_service: DeepResearchService = Depends(get_deep_research_service),
    current_user: dict = Depends(get_current_user),
    limit: Annotated[int, Query(ge=1, le=100, description="返回数量")] = 10,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
    status: Annotated[ResearchStatus | None, Query(description="按状态过滤")] = None,
):
    """获取知识空间的研究历史列表"""
    space, member = validated
    space_id = space.id
    user_id = current_user["id"]

    # 空间管理员可查看所有用户的研究，普通用户只看自己的
    filter_user_id = None if (member and member.is_admin()) else user_id

    # 将 Schema 状态转换为 Model 状态
    model_status = _map_status_to_model(status)

    items, total = await research_service.list_researches(
        space_id=space_id,
        user_id=filter_user_id,
        status=model_status,
        limit=limit,
        offset=offset,
    )

    return ResearchListResponse(
        items=[
            ResearchListItem(
                session_id=item.session_id,
                query=item.query,
                research_topic=_get_research_topic(item),
                status=_map_status_to_schema(item.status),
                research_mode=ResearchMode(item.mode),
                created_at=item.created_at,
                completed_at=item.completed_at,
            )
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{session_id}",
    response_model=ResearchResponse,
    summary="获取研究详情",
    description="获取指定研究会话的详细信息，包括研究主题、任务列表、最终报告和搜索摘要",
)
async def get_research(
    session_id: Annotated[str, Path(min_length=1, description="研究会话ID")],
    validated: tuple = Depends(validate_space_access),
    research_service: DeepResearchService = Depends(get_deep_research_service),
    current_user: dict = Depends(get_current_user),
):
    """获取研究会话详情"""
    space, member = validated
    space_id = space.id
    user_id = current_user["id"]

    is_admin = member.is_admin() if member else False
    research = await research_service.get_research(
        session_id=session_id,
        space_id=space_id,
        user_id=user_id,
        is_admin=is_admin,
    )

    # 构建外部提供商信息
    external_provider = None
    if research.external_provider:
        try:
            external_provider = ExternalSearchProvider(research.external_provider)
        except ValueError:
            external_provider = None

    return ResearchResponse(
        session_id=research.session_id,
        query=research.query,
        research_mode=ResearchMode(research.mode),
        search_source=SearchSource(research.search_source),
        external_provider=external_provider,
        status=_map_status_to_schema(research.status),
        research_topic=_get_research_topic(research),
        research_tasks=_get_research_tasks(research),
        research_plan=_get_research_plan(research),
        final_report=_get_final_report(research),
        search_summary=_get_search_summary(research),
        stats=research.stats or {},
        created_at=research.created_at if research.created_at else None,
        completed_at=research.completed_at if research.completed_at else None,
    )


@router.delete(
    "/{session_id}",
    response_model=UserMessageResponse,
    summary="删除研究记录",
    description="删除指定研究会话记录，普通用户只能删除自己的研究，管理员可删除任意研究",
)
async def delete_research(
    session_id: Annotated[str, Path(min_length=1, description="研究会话ID")],
    validated: tuple = Depends(validate_space_access),
    research_service: DeepResearchService = Depends(get_deep_research_service),
    current_user: dict = Depends(get_current_user),
):
    """删除研究会话记录"""
    space, member = validated
    space_id = space.id
    user_id = current_user["id"]

    is_admin = member.is_admin() if member else False
    await research_service.delete_research(
        session_id=session_id,
        space_id=space_id,
        user_id=user_id,
        is_admin=is_admin,
    )

    return UserMessageResponse(message="研究已删除")
