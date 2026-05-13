"""
应用中心依赖注入
"""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.database import get_db
from src.shared.ai_models.base_model import BaseLLM
from src.features.user.services.model_config_service import ModelConfigService


def _get_model_config_service(db: AsyncSession = Depends(get_db)) -> ModelConfigService:
    return ModelConfigService(db)


async def _get_llm_client(
    model_config_service: ModelConfigService = Depends(_get_model_config_service),
) -> BaseLLM:
    model_name = await model_config_service.get_default_model_name("llm")
    if not model_name:
        raise ValueError("未配置默认 LLM 模型")
    return await model_config_service.get_llm_client_by_model(None, model_name)
