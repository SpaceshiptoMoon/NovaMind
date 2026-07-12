"""
测评模块依赖注入
"""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.database.database import get_db
from novamind.features.knowledge_space.api.dependencies import (
    get_current_user_id,
    validate_space_member,
    validate_space_editor,
    validate_kb_access,
    get_search_service,
)
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.features.evaluation.services.evaluation_service import EvaluationService
from novamind.features.knowledge_space.services.search_service import SearchService
from novamind.shared.clients import get_minio_client


async def get_evaluation_service(
    db: AsyncSession = Depends(get_db),
    search_service: SearchService = Depends(get_search_service),
) -> EvaluationService:
    """获取测评服务"""
    model_config_service = ModelConfigService(db)
    minio_client = await get_minio_client()
    return EvaluationService(
        db=db,
        search_service=search_service,
        model_config_service=model_config_service,
        minio_client=minio_client,
    )
