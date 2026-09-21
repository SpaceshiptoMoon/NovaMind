from fastapi import Depends
from novamind.core.database.database import get_db
from novamind.features.user.repository import UserRepository
from novamind.features.user.services import UserService
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.features.user.services.permission_service import RbacPermissionService
from novamind.features.user.services.role_service import RoleService
from novamind.features.user.services.search_config_service import SearchConfigService
from novamind.shared.storage.client_factory import ClientFactory
from sqlalchemy.ext.asyncio import AsyncSession


async def get_user_service(db: AsyncSession = Depends(get_db)):
    user_repository = UserRepository(db)
    return UserService(user_repository)


async def get_role_service(db: AsyncSession = Depends(get_db)) -> RoleService:
    """获取角色管理服务（RBAC 路由装配点）。

    注入 ``RbacPermissionService``，便于 ``assign_user_role`` 后失效用户权限缓存。
    Redis 客户端未装配时降级为 ``redis_client=None``。
    """
    try:
        redis_client = await ClientFactory.get_redis_client()
    except Exception:
        redis_client = None
    permission_checker = RbacPermissionService(db, redis_client)
    return RoleService(db, permission_checker)


async def get_model_config_service(db: AsyncSession = Depends(get_db)) -> ModelConfigService:
    """获取模型配置服务（路由装配点，返回具体 ModelConfigService）。

    历史上此处注入 ``knowledge_space_info_adapter`` 构造的 KnowledgeSpaceInfoPort
    以解反向依赖；该端口随批次 3.x/4.5 删除后 ModelConfigService 只收 ``db``
    （空间绑定查询已改为 models 直查，见服务内注释）。
    """
    return ModelConfigService(db)


async def get_search_config_service(db: AsyncSession = Depends(get_db)) -> SearchConfigService:
    """获取搜索配置服务（路由装配点）。

    返回具体 ``SearchConfigService``（CRUD 面）；qa 装配点用
    以 ``SearchConfigService`` 直构注入 AIChatService（批次 3.6 去端口）。
    """
    return SearchConfigService(db)


async def get_permission_checker(db: AsyncSession = Depends(get_db)) -> RbacPermissionService:
    """获取权限检查服务（RBAC 装配点）。

    返回 ``RbacPermissionService`` 实例（core/authorization 的
    ``get_permission_checker`` 为同款直构；此装配点供本 feature 内路由使用）。
    Redis 客户端未装配或初始化失败时，降级为 ``redis_client=None``，走 DB 直查。
    """
    try:
        redis_client = await ClientFactory.get_redis_client()
    except Exception:
        redis_client = None
    return RbacPermissionService(db, redis_client)
