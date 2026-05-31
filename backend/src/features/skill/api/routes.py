"""
技能广场 API 路由
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Path, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.user.api.auth import get_current_user, require_admin
from src.core.database.database import get_db
from src.features.user.models.user import User
from src.features.skill.api.dependencies import get_skill_service, update_llm_review_settings, get_llm_review_settings
from src.features.skill.services.skill_marketplace_service import SkillMarketplaceService
from src.features.skill.services.skill_parser import validate_skill_md
from src.features.skill.schemas.skill_schema import (
    SkillResponse,
    SkillListItemResponse,
    SkillMarketplaceListResponse,
    SkillReviewResponse,
    SkillReviewListResponse,
    SkillInstallationResponse,
    SkillValidateResponse,
    SkillInstallRequest,
    SkillReviewCreate,
    SkillValidateRequest,
    SkillAdminSettingsUpdate,
    SkillAdminSettingsResponse,
    SkillAdminReviewAction,
    SkillActionResponse,
    SkillReviewActionResultResponse,
    SkillPendingReviewListResponse,
)
from src.features.skill.exceptions import (
    SkillNotFoundError,
    InvalidSkillFormatError,
    SkillFileSizeExceededError,
)

router = APIRouter()

# ZIP 文件最大大小 (50MB)
MAX_ZIP_SIZE = 50 * 1024 * 1024


async def get_current_user_id(current_user: dict = Depends(get_current_user)) -> int:
    return current_user["id"]


# ==================== 上传 ====================

@router.post(
    "/upload",
    response_model=SkillResponse,
    summary="上传技能 ZIP 包",
    description="上传包含 SKILL.md 的技能 ZIP 包，创建新技能",
)
async def upload_skill(
    file: UploadFile = File(..., description="技能 ZIP 包（含 SKILL.md）"),
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    if not file.filename or not file.filename.endswith(".zip"):
        raise InvalidSkillFormatError("请上传 .zip 格式的文件")

    zip_bytes = await file.read()
    if len(zip_bytes) > MAX_ZIP_SIZE:
        raise SkillFileSizeExceededError(MAX_ZIP_SIZE // 1024 // 1024)
    return await service.upload_skill(user_id, zip_bytes)


@router.put(
    "/{skill_id}/upload",
    response_model=SkillResponse,
    summary="更新技能（上传新版本 ZIP）",
    description="为已有技能上传新版本的 ZIP 包",
)
async def update_skill_version(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    file: UploadFile = File(..., description="新版技能 ZIP 包"),
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    if not file.filename or not file.filename.endswith(".zip"):
        raise InvalidSkillFormatError("请上传 .zip 格式的文件")

    zip_bytes = await file.read()
    if len(zip_bytes) > MAX_ZIP_SIZE:
        raise SkillFileSizeExceededError(MAX_ZIP_SIZE // 1024 // 1024)
    return await service.update_skill_version(user_id, skill_id, zip_bytes)


# ==================== 查询 ====================

@router.get(
    "/mine",
    response_model=SkillMarketplaceListResponse,
    summary="我的技能列表",
    description="获取当前用户上传的所有技能列表",
)
async def list_my_skills(
    status: Annotated[Optional[int], Query(description="状态过滤")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="每页数量")] = 20,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    skills, total = await service.list_my_skills(user_id, status, limit, offset)
    user_ids = list({s.user_id for s in skills if s.user_id})
    user_map = await _batch_get_usernames(service.db, user_ids)
    items = [_skill_to_list_item(s, user_map.get(s.user_id)) for s in skills]
    return SkillMarketplaceListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/marketplace",
    response_model=SkillMarketplaceListResponse,
    summary="广场浏览",
    description="浏览技能广场中所有已发布的技能，支持搜索、分类和排序",
)
async def list_marketplace(
    keyword: Annotated[Optional[str], Query(max_length=200, description="搜索关键词")] = None,
    category: Annotated[Optional[str], Query(max_length=50, description="分类筛选")] = None,
    tags: Annotated[Optional[str], Query(description="标签筛选")] = None,
    sort: Annotated[str, Query(pattern="^(popular|rating|newest|name)$", description="排序方式: popular/rating/newest/name")] = "newest",
    limit: Annotated[int, Query(ge=1, le=100, description="每页数量")] = 20,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    skills, total = await service.list_marketplace(keyword, category, tags, sort, limit, offset)
    user_ids = list({s.user_id for s in skills if s.user_id})
    user_map = await _batch_get_usernames(service.db, user_ids)
    items = [_skill_to_list_item(s, user_map.get(s.user_id)) for s in skills]
    return SkillMarketplaceListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/installed/{agent_id}",
    response_model=list[SkillInstallationResponse],
    summary="Agent 已安装技能",
    description="获取指定 Agent 已安装的所有技能列表",
)
async def list_installed(
    agent_id: Annotated[int, Path(gt=0, description="Agent ID")],
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    return await service.list_installed(agent_id)


# ==================== 验证 ====================

@router.post(
    "/validate",
    response_model=SkillValidateResponse,
    summary="验证 SKILL.md 格式",
    description="验证 SKILL.md 内容格式是否正确，返回解析结果",
)
async def validate_skill(data: SkillValidateRequest):
    result = validate_skill_md(data.content)
    return SkillValidateResponse(
        valid=result.valid,
        errors=result.errors,
        parsed={"name": result.parsed.name, "description": result.parsed.description} if result.parsed else None,
    )


# ==================== 管理员设置（固定路径必须在 /{skill_id} 之前注册）====================

@router.get(
    "/admin/settings",
    response_model=SkillAdminSettingsResponse,
    summary="获取审查设置（管理员）",
    description="获取技能审查的全局设置，包括 LLM 审查开关",
)
async def get_admin_settings(
    _admin: dict = Depends(require_admin),
):
    return await get_llm_review_settings()


@router.put(
    "/admin/settings",
    response_model=SkillAdminSettingsResponse,
    summary="更新审查设置（管理员）",
    description="更新技能审查的全局设置，包括 LLM 审查开关和审查模型",
)
async def update_admin_settings(
    data: SkillAdminSettingsUpdate,
    _admin: dict = Depends(require_admin),
):
    await update_llm_review_settings(data.llm_review_enabled, data.llm_review_model)
    return await get_llm_review_settings()


@router.get(
    "/admin/models",
    response_model=list[str],
    summary="获取可用的 LLM 模型列表（管理员）",
    description="获取管理员配置的 LLM 模型名称列表，用于审查模型选择",
)
async def list_review_models(
    admin_user_id: int = Depends(get_current_user_id),
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from src.features.user.repository.model_config_repository import ModelConfigRepository
    repo = ModelConfigRepository(db)
    configs = await repo.list_by_user(admin_user_id, "llm")
    return [c.model for c in configs]


@router.get(
    "/admin/reviews",
    response_model=SkillPendingReviewListResponse,
    summary="待审核技能列表（管理员）",
    description="获取所有待审核的技能列表",
)
async def list_pending_reviews(
    limit: Annotated[int, Query(ge=1, le=100, description="每页数量")] = 20,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
    _admin: dict = Depends(require_admin),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    skills, total = await service.list_pending_review(limit, offset)
    user_ids = list({s.user_id for s in skills if s.user_id})
    user_map = await _batch_get_usernames(service.db, user_ids)
    return {
        "items": [_skill_to_list_item(s, user_map.get(s.user_id)) for s in skills],
        "total": total,
    }


@router.post(
    "/admin/reviews/{skill_id}/approve",
    response_model=SkillReviewActionResultResponse,
    summary="批准技能（管理员）",
    description="管理员批准待审核的技能",
)
async def approve_skill(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    _admin: dict = Depends(require_admin),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    updated = await service.approve_skill(skill_id)
    return SkillReviewActionResultResponse(success=True, review_status=updated.review_status)


@router.post(
    "/admin/reviews/{skill_id}/reject",
    response_model=SkillReviewActionResultResponse,
    summary="拒绝技能（管理员）",
    description="管理员拒绝待审核的技能，可附上原因",
)
async def reject_skill(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    body: SkillAdminReviewAction = None,
    _admin: dict = Depends(require_admin),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    reason = body.reason if body else None
    updated = await service.reject_skill(skill_id, reason)
    return SkillReviewActionResultResponse(success=True, review_status=updated.review_status)


# ==================== 动态路径 /{skill_id} ====================
@router.get(
    "/{skill_id}",
    response_model=SkillResponse,
    summary="技能详情",
    description="根据技能 ID 获取技能的详细信息",
)
async def get_skill(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    skill = await service.get_skill(skill_id, user_id)
    if not skill:
        raise SkillNotFoundError(skill_id)
    # 填充 author_name
    if skill.user_id:
        user_map = await _batch_get_usernames(service.db, [skill.user_id])
        skill.author_name = user_map.get(skill.user_id)
    return skill


@router.delete(
    "/{skill_id}",
    response_model=SkillActionResponse,
    summary="删除技能",
    description="删除指定的技能及其所有版本数据",
)
async def delete_skill(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    await service.delete_skill(user_id, skill_id)
    return {"success": True, "message": "技能已删除"}


# ==================== 下载 ====================

@router.get(
    "/{skill_id}/download",
    summary="下载技能 ZIP 包",
    description="下载指定技能的 ZIP 包文件",
)
async def download_skill(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    zip_bytes = await service.download_skill(skill_id)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=skill_{skill_id}.zip"},
    )


# ==================== 发布 ====================

@router.post(
    "/{skill_id}/publish",
    response_model=SkillResponse,
    summary="发布技能",
    description="将技能发布到技能广场，供其他用户浏览和安装",
)
async def publish_skill(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    return await service.publish_skill(user_id, skill_id)


@router.post(
    "/{skill_id}/unpublish",
    response_model=SkillResponse,
    summary="取消发布",
    description="将已发布的技能从技能广场撤回",
)
async def unpublish_skill(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    return await service.unpublish_skill(user_id, skill_id)


# ==================== 安装 ====================

@router.post(
    "/{skill_id}/install",
    response_model=SkillInstallationResponse,
    summary="安装到 Agent",
    description="将技能安装到指定的 Agent 上",
)
async def install_skill(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    data: SkillInstallRequest,
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    from src.features.agent.repository.agent_repository import AgentRepository
    agent_repo = AgentRepository(service.db)
    return await service.install_skill(user_id, skill_id, data.agent_id, agent_repo)


@router.delete(
    "/{skill_id}/install/{agent_id}",
    response_model=SkillActionResponse,
    summary="卸载技能",
    description="从指定 Agent 上卸载技能",
)
async def uninstall_skill(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    agent_id: Annotated[int, Path(gt=0, description="Agent ID")],
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    from src.features.agent.repository.agent_repository import AgentRepository
    agent_repo = AgentRepository(service.db)
    await service.uninstall_skill(user_id, skill_id, agent_id, agent_repo)
    return {"success": True, "message": "技能已卸载"}


# ==================== 评价 ====================

@router.post(
    "/{skill_id}/reviews",
    response_model=SkillReviewResponse,
    summary="创建/更新评价",
    description="对指定技能创建或更新评价（评分 + 评论）",
)
async def create_review(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    data: SkillReviewCreate,
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    return await service.create_review(user_id, skill_id, data.rating, data.content)


@router.get(
    "/{skill_id}/reviews",
    response_model=SkillReviewListResponse,
    summary="评价列表",
    description="获取指定技能的评价列表",
)
async def list_reviews(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    limit: Annotated[int, Query(ge=1, le=100, description="每页数量")] = 20,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    reviews, total = await service.list_reviews(skill_id, limit, offset)
    # 批量填充 user_name
    reviewer_ids = list({r.user_id for r in reviews if r.user_id})
    user_map = await _batch_get_usernames(service.db, reviewer_ids)
    for r in reviews:
        if r.user_id and not r.user_name:
            r.user_name = user_map.get(r.user_id)
    return SkillReviewListResponse(items=reviews, total=total)


@router.delete(
    "/{skill_id}/reviews",
    response_model=SkillActionResponse,
    summary="删除评价",
    description="删除当前用户对指定技能的评价",
)
async def delete_review(
    skill_id: Annotated[int, Path(gt=0, description="技能ID")],
    user_id: int = Depends(get_current_user_id),
    service: SkillMarketplaceService = Depends(get_skill_service),
):
    await service.delete_review(user_id, skill_id)
    return {"success": True, "message": "评价已删除"}


# ==================== 管理员审核（POST 路径不会被 /{skill_id} 拦截）====================

async def _batch_get_usernames(db, user_ids: list[int]) -> dict[int, str]:
    """批量查询用户名"""
    if not user_ids:
        return {}
    result = await db.execute(
        select(User.id, User.username).where(User.id.in_(user_ids))
    )
    return dict(result.all())


def _skill_to_list_item(skill, author_name: str | None = None) -> SkillListItemResponse:
    """SkillDefinition → SkillListItemResponse"""
    return SkillListItemResponse(
        id=skill.id,
        name=skill.name,
        display_name=skill.display_name,
        description=skill.description,
        category=skill.category,
        tags=skill.tags,
        icon=skill.icon,
        version=skill.version,
        skill_source=skill.skill_source,
        install_count=skill.install_count,
        rating_avg=skill.rating_avg,
        rating_count=skill.rating_count,
        author_name=author_name,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )
