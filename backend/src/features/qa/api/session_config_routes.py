"""
会话配置 API 路由
"""
from typing import Annotated
from fastapi import APIRouter, Depends, Path, Body, status
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.exc import IntegrityError

from src.core.database.database import get_db
from src.features.user.api.auth import get_current_user
from src.features.qa.api.exceptions import (
    SessionConfigAlreadyExistsError,
    SessionConfigNotFoundError,
    UnauthorizedAccessException,
)
from src.features.qa.repository.session_config_repository import SessionConfigRepository
from src.features.qa.repository.question_answer_repository import QuestionAnswerRepository
from src.features.qa.schemas.session_config import (
    SessionConfigCreate,
    SessionConfigResponse,
)
from src.core.middleware.structured_logging import get_logger

router = APIRouter(tags=["会话配置"])
logger = get_logger(__name__)


async def get_current_user_id(current_user: dict = Depends(get_current_user)) -> int:
    """获取当前用户 ID"""
    return current_user["id"]


def get_session_config_repo(
    db: AsyncSession = Depends(get_db)
) -> SessionConfigRepository:
    """获取会话配置仓库"""
    return SessionConfigRepository(db)


@router.post(
    "",
    response_model=SessionConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建会话配置",
    description="为指定会话创建压缩配置。注意：压缩配置创建后不可修改。",
)
async def create_config(
    session_id: Annotated[str, Path(min_length=1, description="会话 ID")],
    request: Annotated[SessionConfigCreate, Body(...)],
    user_id: int = Depends(get_current_user_id),
    repo: SessionConfigRepository = Depends(get_session_config_repo),
):
    """
    创建会话配置

    压缩配置创建后不可修改，请谨慎设置。

    - **compression.enable_compression**: 是否启用压缩（默认 true）
    - **compression.strategy**: 压缩策略（默认 summary）
    - **compression.threshold**: 触发压缩的 token 阈值（默认 3000）
    - **compression.target_tokens**: 压缩后的目标 token 数（默认 500）
    - **compression.keep_recent**: 保留的最近消息数（默认 2）
    - **compression.custom_prompt**: 自定义摘要提示词（可选）
    """
    # 校验会话归属：如果该 session_id 已有其他用户的消息，则拒绝
    qa_repo = QuestionAnswerRepository(repo.session)
    existing_messages = await qa_repo.get_by_session(session_id)
    if existing_messages and existing_messages[0].user_id != user_id:
        raise UnauthorizedAccessException("无权为此会话创建配置")

    # 检查是否已存在（应用层快速失败）
    existing = await repo.get_by_session_id(session_id)
    if existing:
        raise SessionConfigAlreadyExistsError(session_id)

    # 创建配置（数据库层兜底，防止 TOCTOU 竞态）
    try:
        config = await repo.create(
            session_id=session_id,
            user_id=user_id,
            compression_config=request.compression.model_dump(),
        )
    except IntegrityError:
        raise SessionConfigAlreadyExistsError(session_id)

    logger.info(
        "会话配置已创建",
        session_id=session_id,
        compression_strategy=request.compression.strategy,
    )

    return SessionConfigResponse.model_validate(config)


@router.get(
    "",
    response_model=SessionConfigResponse,
    summary="获取会话配置",
    description="获取指定会话的压缩配置。如果不存在，返回 404。",
)
async def get_config(
    session_id: Annotated[str, Path(min_length=1, description="会话 ID")],
    user_id: int = Depends(get_current_user_id),
    repo: SessionConfigRepository = Depends(get_session_config_repo),
):
    """
    获取会话配置

    如果会话没有配置，返回 404 错误。
    """
    config = await repo.get_by_session_id(session_id)

    if not config:
        raise SessionConfigNotFoundError(session_id)

    # 权限校验
    if config.user_id != user_id:
        raise UnauthorizedAccessException("无权访问此会话配置")

    return SessionConfigResponse.model_validate(config)


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除会话配置",
    description="删除指定会话的压缩配置。",
)
async def delete_config(
    session_id: Annotated[str, Path(min_length=1, description="会话 ID")],
    user_id: int = Depends(get_current_user_id),
    repo: SessionConfigRepository = Depends(get_session_config_repo),
):
    """
    删除会话配置

    删除后会话将使用全局默认配置。
    """
    # 检查配置是否存在及归属
    existing = await repo.get_by_session_id(session_id)
    if not existing:
        # 不存在则直接返回 204
        return None

    if existing.user_id != user_id:
        raise UnauthorizedAccessException("无权操作此会话配置")

    await repo.delete(session_id)
    logger.info("会话配置已删除", session_id=session_id)
    return None
