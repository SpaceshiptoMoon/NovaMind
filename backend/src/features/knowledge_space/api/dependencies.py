"""
依赖注入

提供 API 层的依赖注入函数
支持多租户和知识库层级
使用单例工厂管理客户端实例
"""

from typing import Optional

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.database import get_db
from src.features.user.api.auth import get_current_user
from src.features.user.repository.user_repository import UserRepository
from src.features.knowledge_space.models.space_member import SpaceMember, MemberStatus, SpaceRole
from src.features.knowledge_space.models.knowledge_base import KnowledgeBase, KnowledgeBaseStatus
from src.features.knowledge_space.models.knowledge_space import SpaceVisibility, SpaceStatus
from src.features.user.models.user import User
from src.features.knowledge_space.repository.space_repository import SpaceRepository
from src.features.knowledge_space.repository.member_repository import MemberRepository
from src.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
from src.features.knowledge_space.services.space_service import SpaceService
from src.features.knowledge_space.services.member_service import MemberService
from src.features.knowledge_space.services.document_service import DocumentService
from src.features.knowledge_space.services.knowledge_base_service import KnowledgeBaseService
from src.features.knowledge_space.services.search_service import SearchService
from src.features.knowledge_space.services.audit_service import AuditService
from src.features.user.services.model_config_service import ModelConfigService
from src.shared.utils.time_utils import now_china
from src.features.knowledge_space.api.exceptions import (
    SpaceNotFoundError,
    SpaceAccessDeniedError,
    MemberNotFoundError,
    KnowledgeBaseNotFoundError,
    UserNotFoundError,
)
from src.shared.clients import (
    get_minio_client,
    get_elasticsearch_client,
)


# ========== 请求级缓存 ==========

import contextvars
from typing import Dict, Any

# 使用 contextvars 实现请求级别的用户信息缓存
_request_user_cache: contextvars.ContextVar[Dict[int, Any]] = contextvars.ContextVar(
    "request_user_cache", default=None
)


async def _get_cached_user(
    user_id: int,
    db: AsyncSession,
) -> Optional[User]:
    """
    获取缓存的用户信息（请求级别）

    在同一请求中多次调用时，只查询一次数据库。
    """
    # 获取当前请求的缓存
    cache = _request_user_cache.get() or {}
    if user_id in cache:
        return cache[user_id]

    # 查询数据库
    user = await db.get(User, user_id)

    # 缓存结果
    new_cache = {**cache, user_id: user}
    _request_user_cache.set(new_cache)

    return user


# ========== 基础服务依赖 ==========

async def get_space_service(db: AsyncSession = Depends(get_db)) -> SpaceService:
    """获取空间服务（使用单例客户端，注入模型配置服务）"""
    es_client = await get_elasticsearch_client()
    minio_client = await get_minio_client()
    model_config_service = ModelConfigService(db)
    return SpaceService(
        db,
        es_client=es_client,
        minio_client=minio_client,
        model_config_service=model_config_service,
    )


async def get_member_service(db: AsyncSession = Depends(get_db)) -> MemberService:
    """获取成员服务"""
    es_client = await get_elasticsearch_client()
    minio_client = await get_minio_client()
    return MemberService(db, es_client=es_client, minio_client=minio_client)


async def get_document_service(db: AsyncSession = Depends(get_db)) -> DocumentService:
    """获取文档服务（使用单例客户端）"""
    minio_client = await get_minio_client()
    es_client = await get_elasticsearch_client()
    return DocumentService(session=db, minio_client=minio_client, es_client=es_client)


async def get_knowledge_base_service(db: AsyncSession = Depends(get_db)) -> KnowledgeBaseService:
    """获取知识库服务（使用单例客户端）"""
    es_client = await get_elasticsearch_client()
    minio_client = await get_minio_client()
    return KnowledgeBaseService(
        session=db,
        es_client=es_client,
        minio_client=minio_client,
    )


async def get_search_service(db: AsyncSession = Depends(get_db)) -> SearchService:
    """获取检索服务（使用单例客户端，注入模型配置服务）"""
    es_client = await get_elasticsearch_client()
    model_config_service = ModelConfigService(db)
    return SearchService(
        session=db,
        es_client=es_client,
        model_config_service=model_config_service,
    )


async def get_audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    """获取审计服务"""
    return AuditService(db)


async def get_user_repository(db: AsyncSession = Depends(get_db)) -> UserRepository:
    """获取用户仓储"""
    return UserRepository(db)


async def get_kb_repository(db: AsyncSession = Depends(get_db)) -> KnowledgeBaseRepository:
    """获取知识库仓储"""
    return KnowledgeBaseRepository(db)


# ========== 用户上下文依赖 ==========

async def get_current_user_id(
    current_user: dict = Depends(get_current_user),
) -> int:
    """获取当前用户 ID"""
    return current_user["id"]


# ========== 空间访问验证 ==========

async def validate_space_access(
    space_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> tuple:
    """
    验证用户对空间的访问权限

    Args:
        space_id: 空间 ID
        user_id: 用户 ID
        db: 数据库会话

    Returns:
        (space, member) 元组

    Raises:
        SpaceNotFoundError: 空间不存在
        SpaceAccessDeniedError: 无权访问
    """
    space_repo = SpaceRepository(db)
    member_repo = MemberRepository(db)

    # 获取空间
    space = await space_repo.get_by_id(space_id)
    if not space:
        raise SpaceNotFoundError(space_id)

    # 检查空间是否已被软删除
    if space.is_deleted():
        raise SpaceNotFoundError(space_id)

    # 检查空间状态（归档空间不允许访问）
    if space.status != SpaceStatus.ACTIVE:
        raise SpaceNotFoundError(space_id)

    # 获取用户信息（用于系统管理员检查）- 使用请求级缓存
    user = await _get_cached_user(user_id, db)

    # 系统管理员拥有所有空间的访问权限
    if user and user.is_admin:
        member = await member_repo.get_by_space_and_user(space_id, user_id)
        return space, member

    # 检查是否是成员
    member = await member_repo.get_by_space_and_user(space_id, user_id)

    # 如果不是成员，检查是否是公开空间
    if not member and space.visibility != SpaceVisibility.PUBLIC:
        raise SpaceAccessDeniedError(space_id, user_id)

    return space, member


async def validate_space_member(
    space_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SpaceMember:
    """
    验证用户是空间成员

    Args:
        space_id: 空间 ID
        user_id: 用户 ID
        db: 数据库会话

    Returns:
        成员记录

    Raises:
        SpaceNotFoundError: 空间不存在
        MemberNotFoundError: 不是成员
    """
    space_repo = SpaceRepository(db)
    member_repo = MemberRepository(db)

    # 获取空间
    space = await space_repo.get_by_id(space_id)
    if not space:
        raise SpaceNotFoundError(space_id)

    # 检查空间是否已被软删除
    if space.is_deleted():
        raise SpaceNotFoundError(space_id)

    # 检查空间状态（归档空间不允许访问）
    if space.status != SpaceStatus.ACTIVE:
        raise SpaceNotFoundError(space_id)

    # 系统管理员自动拥有所有空间的成员权限 - 使用请求级缓存
    user = await _get_cached_user(user_id, db)
    if user and user.is_admin:
        member = await member_repo.get_by_space_and_user(space_id, user_id)
        if member is None:
            # 构造虚拟管理员成员（不持久化，仅供权限判断）
            member = SpaceMember(
                id=0,
                space_id=space_id,
                user_id=user_id,
                role=SpaceRole.ADMIN,
                status=MemberStatus.ACTIVE,
                joined_at=now_china(),
            )
        return member

    # 检查成员
    member = await member_repo.get_by_space_and_user(space_id, user_id)
    if not member:
        raise MemberNotFoundError(space_id, user_id)

    return member


async def validate_space_admin(
    space_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SpaceMember:
    """
    验证用户是空间管理员

    使用 SpaceMember.role 枚举字段判断权限。
    系统管理员（is_admin=true）自动拥有所有空间的管理员权限。

    Args:
        space_id: 空间 ID
        user_id: 用户 ID
        db: 数据库会话

    Returns:
        成员记录

    Raises:
        SpaceNotFoundError: 空间不存在
        SpaceAccessDeniedError: 不是管理员
    """
    member = await validate_space_member(space_id, user_id, db)

    # 系统管理员直接放行（使用请求级缓存）
    user = await _get_cached_user(user_id, db)
    if user and user.is_admin:
        return member

    # 基于 SpaceRole 枚举的权限检查
    if member and member.is_admin():
        return member

    raise SpaceAccessDeniedError(space_id, user_id, "需要管理员权限")


async def validate_space_editor(
    space_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SpaceMember:
    """
    验证用户是空间编辑者或更高权限

    系统管理员（is_admin=true）自动拥有编辑者权限。

    Args:
        space_id: 空间 ID
        user_id: 用户 ID
        db: 数据库会话

    Returns:
        成员记录

    Raises:
        SpaceNotFoundError: 空间不存在
        SpaceAccessDeniedError: 不是编辑者或更高权限
    """
    member = await validate_space_member(space_id, user_id, db)

    # 系统管理员直接放行（使用请求级缓存）
    user = await _get_cached_user(user_id, db)
    if user and user.is_admin:
        return member

    if member and member.is_editor_or_above():
        return member

    raise SpaceAccessDeniedError(space_id, user_id, "需要编辑者或更高权限")


# ========== 知识库访问验证 ==========

async def validate_kb_access(
    kb_id: int,
    space_id: int,
    db: AsyncSession,
) -> KnowledgeBase:
    """
    验证知识库访问权限

    注意：此函数设计为可同时用于依赖注入和直接调用。
    依赖注入场景：使用 Depends 包装
    直接调用场景：传入 db 参数

    Args:
        kb_id: 知识库 ID
        space_id: 空间 ID
        db: 数据库会话（必须传入，不使用 Depends 默认值）

    Returns:
        知识库实例

    Raises:
        KnowledgeBaseNotFoundError: 知识库不存在
    """
    kb_repo = KnowledgeBaseRepository(db)
    kb = await kb_repo.get_by_id(kb_id)

    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)

    # 验证空间归属
    if kb.space_id != space_id:
        raise KnowledgeBaseNotFoundError(kb_id)

    # 验证知识库状态
    if kb.status != KnowledgeBaseStatus.ACTIVE:
        raise KnowledgeBaseNotFoundError(kb_id)

    return kb
