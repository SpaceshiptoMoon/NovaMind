from src.core.database.database import get_db
from src.features.qa.services.qa_service import QAService
from src.features.qa.services.qa_cache_service import QACacheService
from src.features.qa.repository.question_answer_repository import QuestionAnswerRepository
from src.features.qa.repository.session_config_repository import SessionConfigRepository
from src.features.qa.repository.session_summary_repository import SessionSummaryRepository
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.features.qa.services.ai_chat_service import AIChatService
from src.features.user.api.dependencies import get_model_config_service
from src.core.middleware.structured_logging import get_logger
from src.shared.clients import get_minio_client

logger = get_logger(__name__)


async def get_minio_client_for_presign():
    """获取 MinIO 客户端（路由层附件预签名用）"""
    try:
        return await get_minio_client()
    except Exception:
        return None


async def get_qa_repository(db: AsyncSession = Depends(get_db)):
    """获取QARepository实例"""
    return QuestionAnswerRepository(db)


async def get_session_config_repository(db: AsyncSession = Depends(get_db)):
    """获取SessionConfigRepository实例"""
    return SessionConfigRepository(db)


async def get_session_summary_repository(db: AsyncSession = Depends(get_db)):
    """获取SessionSummaryRepository实例"""
    return SessionSummaryRepository(db)


async def get_qa_cache_service() -> QACacheService:
    """获取 QACacheService 实例（带 Redis 客户端）"""
    try:
        from src.shared.cache.redis_client import get_redis_client
        redis_client = await get_redis_client()
        return QACacheService(redis_client=redis_client)
    except Exception as e:
        # Redis 不可用时使用纯本地缓存
        logger.warning("Redis 不可用，降级到本地缓存", error=str(e))
        return QACacheService(redis_client=None)


async def get_qa_service(
    repository: QuestionAnswerRepository = Depends(get_qa_repository),
    session_config_repo: SessionConfigRepository = Depends(get_session_config_repository),
    session_summary_repo: SessionSummaryRepository = Depends(get_session_summary_repository),
    cache_service: QACacheService = Depends(get_qa_cache_service),
    model_config_service=Depends(get_model_config_service),
) -> QAService:
    return QAService(
        repository=repository,
        session_config_repo=session_config_repo,
        session_summary_repo=session_summary_repo,
        cache_service=cache_service,
        model_config_service=model_config_service,
    )


async def get_aichat_service(
    qa_service: QAService = Depends(get_qa_service),
    model_config_service=Depends(get_model_config_service),
    db: AsyncSession = Depends(get_db),
) -> AIChatService:
    """
    获取 AI Chat 服务

    通过 ModelConfigService 动态获取模型客户端。
    llm_model 为 None 时使用系统默认模型。
    """
    minio_client = await get_minio_client()
    return AIChatService(
        qa_service=qa_service,
        model_config_service=model_config_service,
        db=db,
        minio_client=minio_client,
    )
