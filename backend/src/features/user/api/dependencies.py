from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from novamind.features.user.services import UserService
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind_engine_core.model_config_ports import ModelConfigPort
from novamind.features.user.repository import UserRepository
from novamind.core.database.database import get_db

async def get_user_service(db: AsyncSession = Depends(get_db)):
    user_repository = UserRepository(db)
    return UserService(user_repository)


async def get_model_config_service(db: AsyncSession = Depends(get_db)) -> ModelConfigPort:
    """获取模型配置服务（装配点：构造具体 ModelConfigService 并注入 KnowledgeSpaceInfoPort，

    以解开 user → knowledge_space.models 的反向依赖；对消费方以 ModelConfigPort 端口暴露）。

    adapter 采用函数内懒导入：顶部 import 会触发
    ``user.api.dependencies → user.adapters.knowledge_space_info_adapter →
    knowledge_space.models → knowledge_space.__init__ → knowledge_space.api →
    user.api.dependencies`` 的循环导入，故下沉到调用点。
    """
    # 装配点允许跨 feature import；懒导入规避循环依赖
    from novamind.features.user.adapters.knowledge_space_info_adapter import (
        as_knowledge_space_info_port,
    )
    return ModelConfigService(db, knowledge_space_info_port=as_knowledge_space_info_port(db))
    