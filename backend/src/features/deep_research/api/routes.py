"""
深度研究 API 路由（只读取面）

批4 工作台统一后，研究执行唯一入口是 agent 对话的 research 工具；
本路由仅保留源发现/列表/详情/删除读取端点，web 写入端点（POST+WS）已清退。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from novamind.core.auth import get_current_user
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.deep_research.api.dependencies import get_deep_research_service
from novamind.features.deep_research.models.research_session import (
    ResearchStatus as ModelResearchStatus,
)
from novamind.features.deep_research.schemas.research_schema import (
    ExternalSearchProvider,
    ResearchListItem,
    ResearchListResponse,
    ResearchMode,
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
from novamind.features.deep_research.services.source_registry import source_registry
from novamind.features.knowledge_space.api.dependencies import validate_space_access
from novamind.features.user.schemas.user_schema import UserMessageResponse

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


def _safe_enum(enum_cls, value, default):
    """存量数据兜底：DB 中遗留非法枚举值时降级为默认而非让列表/详情接口 500
    （对照 model_config 侧 model_type_int_to_str 的降级先例）。"""
    try:
        return enum_cls(value)
    except ValueError:
        return default


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
    """分页列出空间内研究会话（含状态摘要）。"""
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
                research_mode=_safe_enum(ResearchMode, item.mode, ResearchMode.STANDARD),
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
    """读取研究会话全量详情（主题/任务/报告/搜索摘要）。"""
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
        research_mode=_safe_enum(ResearchMode, research.mode, ResearchMode.STANDARD),
        search_source=_safe_enum(SearchSource, research.search_source, SearchSource.HYBRID),
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
    """删除研究记录（本人或管理员）；级联清理产物。"""
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
