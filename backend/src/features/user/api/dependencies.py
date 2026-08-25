from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from novamind.features.user.services import UserService
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.features.user.services.search_config_service import SearchConfigService
from novamind.shared.model_config_ports import ModelConfigPort
from novamind.features.user.repository import UserRepository
from novamind.core.database.database import get_db
from novamind.core.authorization.ports import PermissionCheckerPort
from novamind.features.user.services.permission_service import PermissionService
from novamind.shared.storage.client_factory import ClientFactory

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


async def get_search_config_service(db: AsyncSession = Depends(get_db)) -> SearchConfigService:
    """获取搜索配置服务（路由装配点）。

    返回具体 ``SearchConfigService``（CRUD 面）；qa 装配点用
    ``as_search_config_port`` 以 ``SearchConfigPort`` 端口注入 AIChatService。
    """
    return SearchConfigService(db)


async def get_permission_checker(db: AsyncSession = Depends(get_db)) -> PermissionCheckerPort:
    """获取权限检查服务（RBAC 装配点）。

    返回 ``PermissionService`` 实例，供依赖注入框架以 ``PermissionCheckerPort`` 端口消费。
    Redis 客户端未装配或初始化失败时，降级为 ``redis_client=None``，走 DB 直查。
    """
    try:
        redis_client = await ClientFactory.get_redis_client()
    except Exception:
        redis_client = None
    return PermissionService(db, redis_client)
