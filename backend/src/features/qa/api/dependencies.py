from novamind.core.database.database import get_db
from novamind.features.qa.services.qa_service import QAService
from novamind.features.qa.services.qa_cache_service import QACacheService
from novamind.shared.cache.cache_service import CacheService
from novamind.features.qa.repository.question_answer_repository import QuestionAnswerRepository
from novamind.features.qa.repository.session_config_repository import SessionConfigRepository
from novamind.features.qa.repository.session_summary_repository import SessionSummaryRepository
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from novamind.features.qa.services.ai_chat_service import AIChatService
from novamind.features.user.api.dependencies import get_model_config_service
from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.storage.client_factory import get_minio_client, get_elasticsearch_client
from novamind.features.knowledge_space.services.search_service import SearchService
from novamind.features.knowledge_space.adapters.retrieval_adapter import as_retrieval_port
from novamind.features.knowledge_space.adapters.document_ingestion_adapter import (
    as_document_ingestion_port,
)
from novamind.features.user.adapters.search_config_port_adapter import as_search_config_port

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
    """获取 QACacheService 实例（委托 CacheService 实现 L1+L2）"""
    return QACacheService(cache_service=CacheService())


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
    llm_model 为 None 时使用用户默认模型。

    装配点（批次 5-B2）：检索端口与文档摄入端口在此构造后注入，
    AIChatService 不再内部懒构造。
    """
    minio_client = await get_minio_client()
    es_client = await get_elasticsearch_client()
    search_service = SearchService(db, es_client, model_config_service)
    retrieval_port = as_retrieval_port(search_service)
    ingestion_port = as_document_ingestion_port()
    search_config_port = as_search_config_port(db)
    return AIChatService(
        qa_service=qa_service,
        model_config_service=model_config_service,
        db=db,
        minio_client=minio_client,
        retrieval_port=retrieval_port,
        document_ingestion_port=ingestion_port,
        search_config_port=search_config_port,
    )
