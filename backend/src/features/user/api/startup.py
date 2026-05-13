from fastapi import FastAPI

from src.core.middleware.base_exception_handler import register_module_exceptions
from src.core.middleware.structured_logging import get_logger
from src.features.user.api.exceptions import (
    UserNotFoundError,
    UserAlreadyExistsError,
    UserCreationError,
    UserOperationError,
    AuthenticationError,
    PermissionDeniedError,
    InvalidCredentialsError,
    TokenExpiredError,
    TokenInvalidError,
    UserError,
    ModelConfigDeleteConflictError,
)
from src.features.user.schemas.user_schema import UserUpdate
from src.features.user.services.user_service import UserService
from src.features.user.services.auth_service import AuthService
from src.features.user.repository.user_repository import UserRepository
from src.features.user.models.user import UserStatus
from src.core.database.database import get_db_session
from src.setting.yaml_config import get_config


logger = get_logger(__name__)


async def create_admin_user() -> None:
    """在应用启动时创建默认管理员账户"""
    # 从 YAML 配置读取管理员信息
    config = get_config()
    admin_config = config.admin

    # 检查是否需要创建管理员账户
    if not admin_config.create_on_startup:
        logger.info("跳过创建管理员账户（配置设置）")
        return

    try:
        async with get_db_session() as db:
            user_repo = UserRepository(db)
            user_service = UserService(user_repo)

            # 检查管理员是否已存在
            existing_admin = await user_service.get_user_by_username(
                admin_config.username
            )
            if existing_admin:
                # 已删除的用户不能被恢复
                if existing_admin.status == UserStatus.DELETED:
                    logger.warning("管理员账户已被删除，跳过创建", username=admin_config.username)
                    return
                # 检查是否需要重置密码
                if admin_config.reset_password_if_exists:
                    # 更新管理员密码和角色
                    admin_user_update = UserUpdate(
                        password=admin_config.password,
                        is_admin=True,
                    )
                    await user_service.update_user(
                        user_id=existing_admin.id,
                        user_update=admin_user_update,
                    )
                    # 重置密码后撤销所有已有会话
                    await AuthService.blacklist_all_user_tokens(existing_admin.id)
                    logger.info("管理员账户密码已重置并清除旧会话", username=admin_config.username)
                    logger.warning("管理员邮箱", email=admin_config.email)
                    logger.warning("请及时修改默认管理员密码！")
                else:
                    logger.info("管理员账户已存在", username=admin_config.username)
                return

            # 创建管理员账户
            admin_user = await user_service.create_user(
                username=admin_config.username,
                email=admin_config.email,
                password=admin_config.password,
                phone=admin_config.phone,
                is_admin=True,
            )

            logger.info("管理员账户创建成功", username=admin_config.username)
            logger.info("管理员邮箱", email=admin_config.email)
            logger.warning("首次启动后请及时修改默认管理员密码！")
            logger.warning("生产环境中请修改默认管理员账户信息")

    except Exception as e:
        logger.error("创建管理员账户失败", error=str(e))
        raise


async def init_user_components() -> None:
    """创建管理员账户并同步模型配置"""
    await create_admin_user()
    await sync_model_configs()


async def sync_model_configs() -> None:
    """从 YAML 同步系统模型配置到数据库"""
    from src.features.user.services.model_config_service import ModelConfigService

    try:
        async with get_db_session() as db:
            model_config_service = ModelConfigService(db)
            result = await model_config_service.sync_system_configs_from_yaml()

            if result:
                logger.info("系统模型配置同步完成", result=result)
            else:
                logger.info("无模型配置需要同步")

    except Exception as e:
        logger.error("系统模型配置同步失败", error=str(e))
        raise


def setup_user_exception_handlers(app: FastAPI) -> None:
    """注册用户模块的异常处理器"""
    register_module_exceptions(app, status_map={
        UserNotFoundError: 404,
        UserAlreadyExistsError: 409,
        UserCreationError: 400,
        UserOperationError: 400,
        AuthenticationError: 401,
        PermissionDeniedError: 403,
        InvalidCredentialsError: 401,
        TokenExpiredError: 401,
        TokenInvalidError: 401,
        UserError: 400,
        ModelConfigDeleteConflictError: 409,
    })
