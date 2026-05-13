from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from src.features.user.services import UserService
from src.features.user.services.model_config_service import ModelConfigService
from src.features.user.repository import UserRepository
from src.core.database.database import get_db

async def get_user_service(db: AsyncSession = Depends(get_db)):
    user_repository = UserRepository(db)
    return UserService(user_repository)


async def get_model_config_service(db: AsyncSession = Depends(get_db)) -> ModelConfigService:
    """获取模型配置服务"""
    return ModelConfigService(db)
    