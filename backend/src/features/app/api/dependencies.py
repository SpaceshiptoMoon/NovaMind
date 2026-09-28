"""
应用中心依赖注入
"""
from fastapi import Depends
from novamind.core.database.database import get_db
from novamind.features.knowledge_space.api.dependencies import get_current_user_id
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.ai_models.base_model import BaseLLM
from sqlalchemy.ext.asyncio import AsyncSession


def get_model_config_service(db: AsyncSession = Depends(get_db)) -> ModelConfigService:
    """装配用户模型配置服务（请求级 DB 会话）。"""
    return ModelConfigService(db)


async def _get_llm_client(
    user_id: int = Depends(get_current_user_id),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
) -> BaseLLM:
    """按当前用户默认 LLM 构建客户端；未配置默认模型直接报错（不兜底）。"""
    model_name = await model_config_service.get_user_default_model_name(user_id, "llm")
    if not model_name:
        raise ValueError("未配置 LLM 模型，请先在模型配置中添加")
    return await model_config_service.get_llm_client_by_model(user_id, model_name)
