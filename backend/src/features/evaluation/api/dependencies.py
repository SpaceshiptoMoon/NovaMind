"""
测评模块依赖注入，构造 EvaluationService 所需端口与工厂。
"""
from fastapi import Depends
from novamind.core.database.database import get_db, get_db_session
from novamind.features.evaluation.services.evaluation_service import EvaluationService
from novamind.features.knowledge_space.api.dependencies import (
    get_search_service,
)
from novamind.features.knowledge_space.services.search_service import SearchService
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.storage.client_factory import get_elasticsearch_client, get_minio_client
from sqlalchemy.ext.asyncio import AsyncSession


async def get_evaluation_service(
    db: AsyncSession = Depends(get_db),
    search_service: SearchService = Depends(get_search_service),
) -> EvaluationService:
    """获取测评服务"""
    model_config_service = ModelConfigService(db)
    minio_client = await get_minio_client()

    # 请求级检索端口（fallback 用）
    retrieval_port = search_service

    # 后台任务检索工厂：用独立 session 构造 SearchService（封装 ES + ModelConfigService）
    es_client = await get_elasticsearch_client()

    def retrieval_factory(session: AsyncSession):
        bg_model_config_service = ModelConfigService(session)
        bg_search_service = SearchService(session, es_client, bg_model_config_service)
        return bg_search_service

    return EvaluationService(
        db=db,
        retrieval_port=retrieval_port,
        model_config_service=model_config_service,
        minio_client=minio_client,
        retrieval_factory=retrieval_factory,
        session_factory=get_db_session,
    )