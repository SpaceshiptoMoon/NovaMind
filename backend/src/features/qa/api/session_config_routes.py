"""
会话配置 API 路由
"""
from typing import Annotated
from fastapi import APIRouter, Depends, Path, Body, status
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.exc import IntegrityError

from novamind.core.database.database import get_db
from novamind.features.user.api.auth import get_current_user
from novamind.features.qa.api.exceptions import (
    SessionConfigAlreadyExistsError,
    SessionConfigNotFoundError,
    UnauthorizedAccessException,
)
from novamind.features.qa.repository.session_config_repository import SessionConfigRepository
from novamind.features.qa.repository.question_answer_repository import QuestionAnswerRepository
from novamind.features.qa.services.qa_service import QAService
from novamind.features.qa.api.dependencies import get_qa_service
from novamind.features.qa.schemas.session_config import (
    SessionConfigCreate,
    SessionConfigCompressionUpdate,
    SessionConfigLlmUpdate,
    SessionConfigResponse,
    SessionConfigRagUpdate,
)
from novamind.core.middleware.structured_logging import get_logger

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


async def verify_session_owner(
    session_id: str, user_id: int, repo: SessionConfigRepository,
) -> None:
    """
    会话归属校验（create / PATCH 共用）：若该会话已有其他用户的消息，则拒绝。

    用「消息归属」而非「config 归属」，因为 config 可能尚不存在（首次创建）。
    """
    qa_repo = QuestionAnswerRepository(repo.session)
    existing_messages = await qa_repo.get_by_session(session_id)
    if existing_messages and existing_messages[0].user_id != user_id:
        raise UnauthorizedAccessException("无权操作此会话配置")


@router.post(
    "",
    response_model=SessionConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建会话配置",
    description="为指定会话创建压缩配置。",
)
async def create_config(
    session_id: Annotated[str, Path(min_length=1, description="会话 ID")],
    request: Annotated[SessionConfigCreate, Body(...)],
    user_id: int = Depends(get_current_user_id),
    repo: SessionConfigRepository = Depends(get_session_config_repo),
    qa_service: QAService = Depends(get_qa_service),
):
    """
    创建会话配置

    - **compression.enable_compression**: 是否启用压缩（默认 true）
    - **compression.strategy**: 压缩策略（默认 summary）
    - **compression.threshold**: 触发压缩的 token 阈值（默认 3000）
    - **compression.target_tokens**: 压缩后的目标 token 数（默认 500）
    - **compression.keep_recent**: 保留的最近消息数（默认 2）
    - **compression.custom_prompt**: 自定义摘要提示词（可选）
    """
    # 校验会话归属
    await verify_session_owner(session_id, user_id, repo)

    # 检查是否已存在（应用层快速失败）
    existing = await repo.get_by_session_id(session_id)
    if existing:
        raise SessionConfigAlreadyExistsError(session_id)

    # 创建配置（数据库层兜底，防止 TOCTOU 竞态；qa_service 内部写库 + 失效缓存）
    try:
        config = await qa_service.create_session_config(
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
        # 新会话还没有配置记录，返回默认值（不写库，不报错）
        return SessionConfigResponse(
            id=0,
            session_id=session_id,
            user_id=user_id,
            compression_config={"enable_compression": True, "strategy": "summary", "threshold": 70000, "target_tokens": 2000, "keep_recent": 6, "custom_prompt": None},
            kb_bindings={"space_id": None, "kb_ids": [], "auto_rag": False, "refusal_enabled": False, "score_threshold": 0.3, "search_mode": "content_hybrid", "top_k": 5, "query_rewriting": "none", "grade_retry_enabled": False, "grade_retry_passing_score": 5},
            llm_config={"max_tokens": None, "temperature": None, "top_p": None, "system_prompt": None},
        )

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
    qa_service: QAService = Depends(get_qa_service),
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
    await qa_service.invalidate_session_config_cache(session_id)
    logger.info("会话配置已删除", session_id=session_id)
    return None


@router.patch(
    "/compression-config",
    response_model=SessionConfigResponse,
    summary="更新会话压缩配置",
    description="更新指定会话的压缩配置。支持反复修改，不影响知识库绑定。",
)
async def update_compression_config(
    session_id: Annotated[str, Path(min_length=1, description="会话 ID")],
    request: Annotated[SessionConfigCompressionUpdate, Body(...)],
    user_id: int = Depends(get_current_user_id),
    repo: SessionConfigRepository = Depends(get_session_config_repo),
    qa_service: QAService = Depends(get_qa_service),
):
    """
    更新会话压缩配置

    - **compression.enable_compression**: 是否启用压缩
    - **compression.strategy**: 压缩策略（summary/sliding_window/keep_recent/truncate）
    - **compression.threshold**: 触发压缩的 token 阈值
    - **compression.target_tokens**: 压缩后的目标 token 数
    - **compression.keep_recent**: 保留的最近消息数
    - **compression.custom_prompt**: 自定义摘要提示词（可选）
    """
    # 校验会话归属
    await verify_session_owner(session_id, user_id, repo)

    config = await qa_service.update_compression_config(
        session_id=session_id,
        user_id=user_id,
        compression_config=request.compression.model_dump(),
    )
    logger.info(
        "会话压缩配置已更新",
        session_id=session_id,
        strategy=request.compression.strategy,
    )
    return SessionConfigResponse.model_validate(config)


@router.patch(
    "/llm-config",
    response_model=SessionConfigResponse,
    summary="更新会话模型生成参数配置",
    description="更新指定会话的模型生成参数（max_tokens/temperature/top_p/system_prompt）。支持反复修改，不影响其他配置。",
)
async def update_llm_config(
    session_id: Annotated[str, Path(min_length=1, description="会话 ID")],
    request: Annotated[SessionConfigLlmUpdate, Body(...)],
    user_id: int = Depends(get_current_user_id),
    repo: SessionConfigRepository = Depends(get_session_config_repo),
    qa_service: QAService = Depends(get_qa_service),
):
    """
    更新会话模型生成参数配置

    - **llm_config.max_tokens**: 最大生成 token 数（None 用默认 2048）
    - **llm_config.temperature**: 温度（None 用默认 0.7）
    - **llm_config.top_p**: Top-P（None 用默认 0.8）
    - **llm_config.system_prompt**: 系统提示词（None 用后端 QA 模板）

    注意：llm_model / enable_thinking 由前端请求传，不在此接口。
    """
    # 校验会话归属
    await verify_session_owner(session_id, user_id, repo)

    config = await qa_service.update_llm_config(
        session_id=session_id,
        user_id=user_id,
        llm_config=request.llm_config.model_dump(),
    )
    logger.info(
        "会话模型生成参数配置已更新",
        session_id=session_id,
        temperature=request.llm_config.temperature,
    )
    return SessionConfigResponse.model_validate(config)


@router.patch(
    "/rag-config",
    response_model=SessionConfigResponse,
    summary="更新会话知识库绑定（会话级自动 RAG）",
    description="绑定或更新指定会话的知识库列表，开启后该会话无需每次手动开关即可自动检索。独立于压缩配置，可反复修改。",
)
async def update_rag_config(
    session_id: Annotated[str, Path(min_length=1, description="会话 ID")],
    request: Annotated[SessionConfigRagUpdate, Body(...)],
    user_id: int = Depends(get_current_user_id),
    repo: SessionConfigRepository = Depends(get_session_config_repo),
    qa_service: QAService = Depends(get_qa_service),
):
    """
    绑定/更新会话的知识库（会话级自动 RAG）

    - **rag.space_id**: 知识空间 ID
    - **rag.kb_ids**: 绑定的知识库 ID 列表
    - **rag.auto_rag**: 是否启用自动检索（默认 false）
    - **rag.refusal_enabled**: 是否启用分级拒答（默认 false）
    - **rag.score_threshold**: 低置信度阈值（默认 0.3，单库模式生效）
    - **rag.search_mode**: 检索模式（默认 content_hybrid）
    - **rag.top_k**: 检索返回条数（默认 5）
    """
    # 校验会话归属
    await verify_session_owner(session_id, user_id, repo)

    config = await qa_service.upsert_rag_binding(
        session_id=session_id,
        user_id=user_id,
        rag_config=request.rag.model_dump(),
    )
    logger.info(
        "会话知识库绑定已更新",
        session_id=session_id,
        kb_count=len(request.rag.kb_ids),
        auto_rag=request.rag.auto_rag,
    )
    return SessionConfigResponse.model_validate(config)
