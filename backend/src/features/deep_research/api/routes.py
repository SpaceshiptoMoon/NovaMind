"""
深度研究 API 路由
"""

from fastapi import APIRouter, Depends, Query, Path
from fastapi.responses import StreamingResponse
from typing import Annotated, Optional

from novamind.features.user.api.auth import get_current_user
from novamind.features.knowledge_space.api.dependencies import validate_space_access
from novamind.features.deep_research.api.dependencies import get_deep_research_service
from novamind.features.deep_research.services.deep_research_service import DeepResearchService
from novamind.features.deep_research.schemas.research_schema import (
    ResearchMode,
    SearchSource,
    ExternalSearchProvider,
    ResearchRequest,
    ResearchResponse,
    ResearchListResponse,
    ResearchListItem,
    ResearchStatus,
)
from novamind.features.deep_research.models.research_session import (
    ResearchStatus as ModelResearchStatus,
)
from novamind.features.user.schemas.user_schema import MessageResponse
from novamind.core.middleware.structured_logging import get_logger

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


def _map_status_to_model(status: Optional[ResearchStatus]) -> Optional[ModelResearchStatus]:
    """映射 Schema 状态到 Model 状态"""
    if status is None:
        return None
    return _STATUS_TO_MODEL.get(status)


def _map_status_to_schema(status: ModelResearchStatus) -> ResearchStatus:
    """映射 Model 状态到 Schema 状态"""
    return _STATUS_TO_SCHEMA.get(status, ResearchStatus.PENDING)


# ==================== 辅助函数 ====================

def _get_research_topic(research) -> Optional[str]:
    """从 research 的 config 中获取研究主题"""
    config = research.config or {}
    return config.get("research_topic")


def _get_research_tasks(research) -> Optional[list]:
    """从 research 的 plan 中获取研究任务"""
    plan = research.plan or {}
    return plan.get("tasks")


def _get_final_report(research) -> Optional[str]:
    """从 research 的 result 中获取最终报告"""
    result = research.result or {}
    return result.get("answer")


def _get_search_summary(research) -> Optional[dict]:
    """从 research 的 result 中获取搜索摘要"""
    result = research.result or {}
    if result:
        return {
            "search_results": result.get("search_results", []),
            "sources": result.get("sources", []),
        }
    return None


# ==================== API 路由 ====================

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
            "search_mode": "content_hybrid",
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


@router.post(
    "/stream",
    response_class=StreamingResponse,
    summary="执行深度研究（流式）",
    description="基于知识空间执行深度研究，流式返回进度和报告内容",
)
async def execute_research_stream(
    request: ResearchRequest,
    validated: tuple = Depends(validate_space_access),
    research_service: DeepResearchService = Depends(get_deep_research_service),
    current_user: dict = Depends(get_current_user),
):
    """
    执行深度研究（流式 SSE）

    返回 Server-Sent Events (SSE) 格式的流式数据

    事件类型：
    - progress: 进度更新
    - content: 报告内容片段
    - error: 错误信息
    - done: 研究完成
    """
    space, member = validated
    space_id = space.id
    user_id = current_user["id"]

    async def generate():
        async for chunk in research_service.research_stream(
            space_id=space_id,
            user_id=user_id,
            request=request,
        ):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    status: Annotated[Optional[ResearchStatus], Query(description="按状态过滤")] = None,
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
        final_report=_get_final_report(research),
        search_summary=_get_search_summary(research),
        stats=research.stats or {},
        created_at=research.created_at if research.created_at else None,
        completed_at=research.completed_at if research.completed_at else None,
    )


@router.delete(
    "/{session_id}",
    response_model=MessageResponse,
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

    return MessageResponse(message="研究已删除")
