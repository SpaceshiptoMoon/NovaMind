"""QA 依赖注入装配：AIChatService（聊天附件共享链）FastAPI Depends 工厂。"""
from fastapi import Depends
from novamind.core.database.database import get_db
from novamind.engines.document.pipeline import DocumentProcessor
from novamind.features.knowledge_space.services.instrumented_search_service import (
    InstrumentedSearchService as SearchService,
)
from novamind.features.qa.services.ai_chat_service import AIChatService
from novamind.features.user.api.dependencies import get_model_config_service
from novamind.features.user.services.search_config_service import SearchConfigService
from novamind.shared.storage.client_factory import get_elasticsearch_client, get_minio_client
from sqlalchemy.ext.asyncio import AsyncSession


async def get_aichat_service(
    model_config_service=Depends(get_model_config_service),
    db: AsyncSession = Depends(get_db),
) -> AIChatService:
    """装配 AIChatService（聊天附件服务）。

    Args:
        model_config_service: 模型配置服务（models 端点经路由层直用；
            注入 service 保留装配面）。
        db: 请求级数据库会话（附件记录读写）。

    Returns:
        装配完成的 AIChatService。
    """
    minio_client = await get_minio_client()
    es_client = await get_elasticsearch_client()
    search_service = SearchService(db, es_client, model_config_service)
    document_processor = DocumentProcessor()
    search_config_service = SearchConfigService(db)
    return AIChatService(
        model_config_service=model_config_service,
        db=db,
        minio_client=minio_client,
        search_service=search_service,
        document_processor=document_processor,
        search_config_service=search_config_service,
    )
