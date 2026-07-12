"""
知识库管理路由

处理知识库的创建、更新、删除等操作
支持多租户和 RBAC 权限控制

路由前缀: /api/v1/spaces/{space_id}/knowledge-bases

权限要求:
- 查看知识库列表/详情: VIEWER(0)+
- 创建/编辑知识库: EDITOR(1)+
- 删除知识库: ADMIN(2)
"""

from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Request, Query, Path

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.database.database import get_db
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
    KnowledgeBaseListResponse,
    KnowledgeBaseConfigUpdate,
    KnowledgeBaseConfigResponse,
)
from novamind.features.knowledge_space.schemas.member_schema import ActionResponse
from novamind.features.knowledge_space.models.space_member import SpaceMember
from novamind.features.knowledge_space.api.dependencies import (
    get_current_user_id,
    validate_space_member,
    validate_space_editor,
    validate_space_admin,
    validate_kb_access,
    validate_kb_writable,
    get_kb_repository,
    get_audit_service,
    get_knowledge_base_service,
)
from novamind.features.knowledge_space.api.exceptions import (
    KnowledgeBaseNotFoundError,
)
from novamind.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
from novamind.features.knowledge_space.services.knowledge_base_service import KnowledgeBaseService
from novamind.features.knowledge_space.services.audit_service import AuditService

router = APIRouter(tags=["知识库管理"])



@router.get(
    "",
    response_model=KnowledgeBaseListResponse,
    summary="获取知识库列表",
    description="获取空间内的知识库列表（需要空间成员权限）",
)
async def list_knowledge_bases(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    status: Annotated[Optional[int], Query(description="状态过滤: 1-活跃, 2-已归档")] = None,
    skip: Annotated[int, Query(ge=0, description="跳过的记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=1000, description="返回的最大记录数")] = 100,
    member: SpaceMember = Depends(validate_space_member),
    kb_repo: KnowledgeBaseRepository = Depends(get_kb_repository),
    kb_service = Depends(get_knowledge_base_service),
):
    """获取知识库列表"""
    knowledge_bases = await kb_repo.get_by_space(
        space_id=space_id,
        status=status,
        skip=skip,
        limit=limit,
    )

    # 获取符合条件的总数（用于分页）
    total = await kb_repo.count_by_space(space_id=space_id, status=status)

    # 批量获取所有 KB 的统计信息（单条 SQL，避免 N+1）
    kb_ids = [kb.id for kb in knowledge_bases]
    stats_map = await kb_service.doc_repo.batch_get_kb_stats(kb_ids)

    items = []
    for kb in knowledge_bases:
        resp = KnowledgeBaseResponse.model_validate(kb)
        resp.stats = stats_map.get(kb.id, {
            "document_count": 0,
            "chunk_count": 0,
            "total_size_mb": 0,
            "uploaded_documents": 0,
            "completed_documents": 0,
            "failed_documents": 0,
            "processing_documents": 0,
        })
        items.append(resp)

    return KnowledgeBaseListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{kb_id}",
    response_model=KnowledgeBaseResponse,
    summary="获取知识库详情",
    description="获取指定知识库的详细信息（需要空间成员权限）",
)
async def get_knowledge_base(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    member: SpaceMember = Depends(validate_space_member),
    db: AsyncSession = Depends(get_db),
    kb_service = Depends(get_knowledge_base_service),
):
    """获取知识库详情"""
    kb = await validate_kb_access(kb_id, space_id, db)
    stats = await kb_service.get_full_stats(kb_id)
    response = KnowledgeBaseResponse.model_validate(kb)
    response.stats = stats
    return response


@router.post(
    "",
    response_model=KnowledgeBaseResponse,
    summary="创建知识库",
    description="在空间内创建知识库（需要编辑者或更高权限）",
)
async def create_knowledge_base(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    data: KnowledgeBaseCreate,
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service),
    audit_service: AuditService = Depends(get_audit_service),
):
    """创建知识库"""
    kb = await kb_service.create_knowledge_base(
        space_id=space_id,
        creator_id=user_id,
        name=data.name,
        config=data.config.model_dump() if data.config else None,
    )

    # 记录审计日志
    await audit_service.log_kb_create(
        space_id=space_id,
        user_id=user_id,
        kb_id=kb.id,
        kb_name=kb.name,
        request=request,
    )

    return KnowledgeBaseResponse.model_validate(kb)


@router.put(
    "/{kb_id}",
    response_model=KnowledgeBaseResponse,
    summary="更新知识库",
    description="更新知识库配置（需要编辑者或更高权限）",
)
async def update_knowledge_base(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    data: KnowledgeBaseUpdate,
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service),
    audit_service: AuditService = Depends(get_audit_service),
    db: AsyncSession = Depends(get_db),
):
    """更新知识库"""
    # 验证知识库访问权限
    await validate_kb_writable(kb_id, space_id, db)

    # 构建更新数据（仅包含实际提交的字段）
    update_data = data.model_dump(exclude_unset=True)
    if data.config is not None:
        update_data["config"] = data.config.model_dump()

    kb = await kb_service.update_knowledge_base(
        kb_id=kb_id,
        user_id=user_id,
        data=update_data,
    )

    # 记录审计日志
    await audit_service.log_kb_update(
        space_id=space_id,
        user_id=user_id,
        kb_id=kb_id,
        changes=update_data,
        request=request,
    )

    return KnowledgeBaseResponse.model_validate(kb)


@router.delete(
    "/{kb_id}",
    response_model=ActionResponse,
    summary="删除知识库",
    description="删除知识库（需要空间管理员权限）",
)
async def delete_knowledge_base(
    request: Request,
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_admin),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service),
    audit_service: AuditService = Depends(get_audit_service),
    db: AsyncSession = Depends(get_db),
):
    """删除知识库"""
    # 验证知识库访问权限
    kb = await validate_kb_access(kb_id, space_id, db)
    kb_name = kb.name

    # 记录审计日志（在删除之前记录，因为删除后无法获取名称）
    await audit_service.log_kb_delete(
        space_id=space_id,
        user_id=user_id,
        kb_id=kb_id,
        kb_name=kb_name,
        request=request,
    )

    # 删除知识库
    await kb_service.delete_knowledge_base(
        kb_id=kb_id,
        user_id=user_id,
    )

    return ActionResponse(success=True, message=f"知识库 '{kb_name}' 已删除")


# ========== 配置管理路由 ==========


@router.get(
    "/{kb_id}/config",
    response_model=KnowledgeBaseConfigResponse,
    summary="获取知识库配置",
    description="获取知识库完整配置及统计信息",
)
async def get_knowledge_base_config(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    member: SpaceMember = Depends(validate_space_member),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service),
    db: AsyncSession = Depends(get_db),
):
    """获取知识库配置"""
    kb = await validate_kb_access(kb_id, space_id, db)

    stats = await kb_service.get_full_stats(kb_id)

    return KnowledgeBaseConfigResponse(
        kb_id=kb.id,
        name=kb.name,
        config=kb.get_config(),
        stats=stats,
    )


@router.patch(
    "/{kb_id}/config",
    response_model=KnowledgeBaseConfigResponse,
    summary="更新知识库配置",
    description="部分更新知识库配置（深度合并，只传要改的字段）",
)
async def update_knowledge_base_config(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    config_update: KnowledgeBaseConfigUpdate,
    member: SpaceMember = Depends(validate_space_editor),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service),
    db: AsyncSession = Depends(get_db),
):
    """部分更新知识库配置"""
    kb = await validate_kb_access(kb_id, space_id, db)

    await kb_service.update_config(
        kb_id=kb_id,
        config_updates=config_update.model_dump(exclude_unset=True),
    )

    # 刷新获取最新配置
    await db.refresh(kb)

    stats = await kb_service.get_full_stats(kb_id)

    return KnowledgeBaseConfigResponse(
        kb_id=kb.id,
        name=kb.name,
        config=kb.get_config(),
        stats=stats,
    )
