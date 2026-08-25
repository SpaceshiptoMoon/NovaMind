from fastapi import FastAPI

from novamind.core.middleware.base_exception_handler import register_module_exceptions
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.user.exceptions import (
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
    SearchConfigNotFoundError,
    SearchConfigAlreadyExistsError,
    SearchConfigTestFailedError,
    SearchConfigError,
)
from novamind.features.user.schemas.user_schema import UserUpdate
from novamind.features.user.services.user_service import UserService
from novamind.features.user.services.auth_service import AuthService
from novamind.features.user.repository.user_repository import UserRepository
from novamind.features.user.models.user import UserStatus
from novamind.features.user.models.role import Role, Permission, RolePermission
from novamind.core.database.database import get_db_session
from novamind.core.authorization.permission_codes import SystemPermission, PRESET_ROLE_PERMISSIONS
from novamind.setting.yaml_config import get_config


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

            # 创建管理员账户（保留调用以触发建库副作用；返回值未使用）
            await user_service.create_user(
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


async def _init_rbac_seed(db) -> None:
    """幂等创建预置角色/权限/映射。"""
    from sqlalchemy import select, func

    is_sqlite = db.bind.dialect.name == "sqlite"

    async def _next_id(model_cls):
        """SQLite 下 BigInteger autoincrement 不工作，手动分配自增 ID。"""
        if not is_sqlite:
            return None
        max_id = (await db.execute(select(func.max(model_cls.id)))).scalar()
        return (max_id or 0) + 1

    # 1. 权限项
    existing_perm_codes = set((await db.execute(select(Permission.code))).scalars().all())
    for code in SystemPermission.ALL:
        if code not in existing_perm_codes:
            perm = Permission(code=code, name=_PERM_META[code]["name"], module=_PERM_META[code]["module"])
            perm_id = await _next_id(Permission)
            if perm_id is not None:
                perm.id = perm_id
            db.add(perm)
    await db.flush()

    # 2. 预置角色
    existing_role_codes = set((await db.execute(select(Role.code))).scalars().all())
    for code in ("admin", "editor", "viewer"):
        if code not in existing_role_codes:
            role = Role(code=code, name=_ROLE_NAMES[code], is_system=True)
            role_id = await _next_id(Role)
            if role_id is not None:
                role.id = role_id
            db.add(role)
    await db.flush()

    # 3. 角色权限映射（仅对系统预置角色按 PRESET 配置，已存在的映射不重复加）
    roles = {r.code: r for r in (await db.execute(select(Role))).scalars().all()}
    perms = {p.code: p for p in (await db.execute(select(Permission))).scalars().all()}
    for role_code, perm_codes in PRESET_ROLE_PERMISSIONS.items():
        role = roles[role_code]
        existing = set((await db.execute(
            select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
        )).scalars().all())
        for pc in perm_codes:
            if perms[pc].id not in existing:
                db.add(RolePermission(role_id=role.id, permission_id=perms[pc].id))
    await db.flush()


_PERM_META = {
    "user.manage": {"name": "用户管理", "module": "user"},
    "skill.review": {"name": "技能审核", "module": "skill"},
    "skill.config": {"name": "技能配置", "module": "skill"},
    "agent.manage_system": {"name": "系统级Agent管理", "module": "agent"},
    "role.manage": {"name": "角色管理", "module": "user"},
}

_ROLE_NAMES = {"admin": "管理员", "editor": "编辑者", "viewer": "浏览者"}


async def _migrate_is_admin_to_role(db) -> None:
    """迁移现有用户：原 is_admin=True→admin，False→viewer。幂等。
    在删 is_admin 列前调用（若列已删则跳过）。"""
    from sqlalchemy import select, text

    # 检测 is_admin 列是否存在（旧库迁移场景）
    has_col = False
    try:
        await db.execute(text("SELECT is_admin FROM users LIMIT 1"))
        has_col = True
    except Exception:
        has_col = False

    if not has_col:
        return  # 新库或已迁移

    admin_role = (await db.execute(select(Role).where(Role.code == "admin"))).scalar_one_or_none()
    viewer_role = (await db.execute(select(Role).where(Role.code == "viewer"))).scalar_one_or_none()
    if not admin_role or not viewer_role:
        return

    # is_admin=True 且 role_id 为空 → 绑 admin；其余未绑 → 绑 viewer
    # 使用 IS TRUE 兼容 PostgreSQL boolean 与 SQLite；role_id 使用 bindparam 防止注入。
    await db.execute(
        text("UPDATE users SET role_id = :admin_id WHERE is_admin IS TRUE AND role_id IS NULL"),
        {"admin_id": admin_role.id},
    )
    await db.execute(
        text("UPDATE users SET role_id = :viewer_id WHERE role_id IS NULL"),
        {"viewer_id": viewer_role.id},
    )
    await db.flush()


async def _drop_legacy_is_admin_column(db) -> None:
    """幂等删除 users.is_admin 遗留列（新库或已删则跳过）。"""
    from sqlalchemy import text

    try:
        await db.execute(text("SELECT is_admin FROM users LIMIT 1"))
    except Exception:
        return  # 列已不存在

    try:
        await db.execute(text("ALTER TABLE users DROP COLUMN is_admin"))
        await db.flush()
        logger.info("schema 迁移：删除遗留列 users.is_admin")
    except Exception as e:
        logger.warning("删除 users.is_admin 列失败", error=str(e))


async def init_user_components() -> None:
    """初始化用户模块：RBAC 预置 seed、is_admin→role 迁移、删遗留列、默认管理员账户。"""
    async with get_db_session() as db:
        await _init_rbac_seed(db)
        await _migrate_is_admin_to_role(db)
        await _drop_legacy_is_admin_column(db)
    await create_admin_user()


def setup_auth_port_wiring(app: FastAPI) -> None:
    """装配 core/auth 认证端口与 RBAC 权限端口。

    把 user 的 ``UserStatusResolver`` 实现注册为
    ``core/auth/dependencies.get_user_status_resolver`` 的 dependency_overrides，
    使 core/auth 的认证依赖能经端口取 DB 用户状态，无需 core 反向依赖 user。

    同时把 ``PermissionService`` 注册为 ``PermissionCheckerPort`` 的默认实现，
    供各 feature 路由守卫注入使用。
    """
    # 懒导入规避启动期循环依赖
    from novamind.core.auth.dependencies import get_user_status_resolver
    from novamind.features.user.adapters.auth_user_resolver_adapter import (
        as_user_status_resolver,
    )
    from novamind.core.authorization.ports import PermissionCheckerPort
    from novamind.features.user.api.dependencies import get_permission_checker

    app.dependency_overrides[get_user_status_resolver] = as_user_status_resolver
    app.dependency_overrides[PermissionCheckerPort] = get_permission_checker


def setup_user_exception_handlers(app: FastAPI) -> None:
    """注册用户模块的异常处理器 + 装配 core/auth 认证端口"""
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
        # 搜索配置异常（http_status_code ClassVar 已声明，status_map 注册日志标签 + 兜底）
        SearchConfigNotFoundError: 404,
        SearchConfigAlreadyExistsError: 409,
        SearchConfigTestFailedError: 400,
        SearchConfigError: 400,
    })
    setup_auth_port_wiring(app)
