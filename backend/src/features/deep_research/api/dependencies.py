"""
深度研究依赖注入
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.database.database import get_db
from novamind.features.deep_research.services.deep_research_service import DeepResearchService
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.clients import get_elasticsearch_client


async def get_deep_research_service(
    db: AsyncSession = Depends(get_db)
):
    """获取深度研究服务（请求结束时自动清理资源）"""
    model_config_service = ModelConfigService(db)
    es_client = await get_elasticsearch_client()
    service = DeepResearchService(
        db,
        model_config_service=model_config_service,
        es_client=es_client,
    )
    yield service
    await service.cleanup()
