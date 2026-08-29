from typing import Optional, List, Dict, Any

from sqlalchemy import update

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.user.models.user import User as UserModel, UserStatus
from novamind.features.user.schemas.user_schema import UserUpdate
from novamind.features.user.repository.user_repository import UserRepository
from novamind.features.user.exceptions import (
    UserAlreadyExistsError,
    UserNotFoundError,
    UserCreationError,
    UserOperationError,
    AuthenticationError,
    UserError,
)
from novamind.features.user.services.auth_service import AuthService
from novamind.setting.yaml_config import get_config


class UserService:
    """
    用户服务层，负责处理用户相关的业务逻辑
    包括用户创建、查询、认证、更新等功能
    """

    def __init__(self, user_repository: UserRepository):
        """
        初始化用户服务
        Args:
            user_repository: 用户仓库实例，用于数据持久化操作
        """
        self.logger = get_logger(__name__)
        self.user_repository = user_repository

    async def create_user(
        self,
        username: str,
        email: str,
        password: str,
        phone: Optional[str] = None,
        status: Optional[int] = 1,
        role_code: str = "viewer",
    ) -> Optional[UserModel]:
        """
        创建新用户
        Args:
            username: 用户名
            email: 邮箱
            password: 密码
            phone: 电话号码（可选）
            status: 用户状态（可选，默认为1）
            role_code: 角色编码（可选，默认为 viewer）

        Returns:
            User: 创建成功的用户对象，如果创建失败则抛出异常
        Raises:
            UserAlreadyExistsError: 如果用户名已存在
            UserCreationError: 如果创建过程中发生错误
        """
        try:
            # 检查用户名是否已存在（包含软删除用户，防止唯一约束冲突）
            existing_user = await self.check_user_exists(username)
            if existing_user:
                raise UserAlreadyExistsError(f"用户名 {username} 已存在")

            # 检查邮箱是否已存在（包含软删除用户）
            existing_email = await self.user_repository.get_user_by_email(email, use_cache=False, include_deleted=True)
            if existing_email:
                raise UserAlreadyExistsError(f"邮箱 {email} 已被注册", field="email")

            # 检查手机号是否已存在（包含软删除用户）
            if phone:
                existing_phone = await self.user_repository.get_user_by_phone(phone, include_deleted=True)
                if existing_phone:
                    raise UserAlreadyExistsError(f"手机号 {phone} 已被注册", field="phone")

            # 根据角色编码查询角色，绑定 role_id
            role = await self.user_repository.get_role_by_code(role_code)
            if not role:
                raise UserCreationError(f"角色 {role_code} 不存在")

            # 创建新用户（密码哈希在 Service 层处理）
            from novamind.core.auth.hashing import get_password_hash_async
            user_create = {
                "username": username,
                "email": email,
                "password": await get_password_hash_async(password),
                "phone": phone,
                "status": status,
                "role_id": role.id,
            }
            user = await self.user_repository.create_user(user_create)
            # 记录用户创建成功（关键业务事件）
            self.logger.info("用户创建成功", user_id=user.id, role_code=role_code)
            return user
        except UserAlreadyExistsError:
            # 用户已存在，直接重新抛出异常
            raise
        except Exception as e:
            self.logger.error("创建用户失败", error=str(e))
            raise UserCreationError(f"创建用户失败: {str(e)}")

    async def register_user(
        self,
        username: str,
        email: str,
        password: str,
        phone: Optional[str] = None,
        status: Optional[int] = 1,
    ) -> Optional[UserModel]:
        """
        用户自注册（强制 viewer 角色）

        Args:
            username: 用户名
            email: 邮箱
            password: 密码
            phone: 电话号码（可选）
            status: 用户状态（可选，默认为1）

        Returns:
            User: 创建成功的用户对象
        """
        return await self.create_user(
            username=username,
            email=email,
            password=password,
            phone=phone,
            status=status,
            role_code="viewer",
        )

    async def get_user_by_id(self, user_id: int) -> Optional[UserModel]:
        """
        根据用户ID获取用户信息
        Args:
            user_id: 用户ID

        Returns:
            User: 匹配的用户对象，如果不存在则抛出异常
        Raises:
            UserNotFoundError: 如果用户不存在
        """
        user = await self.user_repository.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(user_id=user_id)
        return user

    async def get_user_by_username(self, username: str) -> Optional[UserModel]:
        """
        根据用户名获取用户信息
        Args:
            username: 用户名

        Returns:
            User: 匹配的用户对象，如果不存在则抛出异常
        Raises:
            UserNotFoundError: 如果用户不存在
        """
        try:
            user = await self.user_repository.get_user_by_username(username)
            return user

        except UserError:
            raise
        except Exception as e:
            self.logger.error("获取用户失败", username=username, error=str(e))
            raise UserOperationError(f"获取用户失败: {str(e)}")

    async def get_users(self, skip: int = 0, limit: int = 100) -> List[UserModel]:
        """
        获取用户列表
        Args:
            skip: 跳过的记录数，默认为0
            limit: 返回的最大记录数，默认为100

        Returns:
            List[User]: 用户对象列表
        """
        try:
            users = await self.user_repository.get_users(skip, limit)
            return users

        except UserError:
            raise
        except Exception as e:
            self.logger.error("获取用户列表失败", error=str(e))
            raise UserOperationError(f"获取用户列表失败: {str(e)}")

    async def authenticate_user(
        self, username: str, password: str
    ) -> Optional[UserModel]:
        """
        认证用户
        Args:
            username: 用户名
            password: 密码

        Returns:
            User: 认证成功的用户对象，如果认证失败则返回None
        Raises:
            AuthenticationError: 如果认证失败
        """

        try:
            user = await self.user_repository.authenticate_user(username, password)
            if not user:
                # 不记录具体用户名，防止用户枚举攻击
                raise AuthenticationError("用户名或密码错误")
            # 记录认证成功（关键业务事件）
            self.logger.info("用户认证成功", user_id=user.id)
            return user
        except AuthenticationError:
            raise
        except Exception as e:
            self.logger.error("认证失败", username=username, error=str(e))
            raise AuthenticationError(f"认证失败: {str(e)}")

    async def login_user(self, username: str, password: str, ip_address: str = None) -> Optional[dict]:
        """
        用户登录

        Args:
            username: 用户名
            password: 密码
            ip_address: 登录IP地址（可选）

        Returns:
            dict: 包含 access_token, refresh_token 和用户信息的字典
        """
        try:
            user = await self.authenticate_user(username, password)
            if user:
                config = get_config()

                # 创建 access token 和 refresh token 对
                role_code = user.role.code if user.role else "viewer"
                access_token, refresh_token = await AuthService.create_token_pair(
                    user_id=user.id,
                    username=user.username,
                    email=user.email,
                    role_code=role_code,
                    status=user.status,
                )

                # 更新登录信息（最后登录时间、IP、登录次数）
                if ip_address:
                    await self.user_repository.update_login_info(user.id, ip_address)

                # 记录登录成功（关键业务事件）
                self.logger.info("用户登录成功", user_id=user.id)

                return {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "token_type": "bearer",
                    "expires_in": config.security.access_token_expire_minutes * 60,
                    "must_change_password": user.must_change_password,
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "role_code": role_code,
                        "is_admin": role_code == "admin",
                    },
                }

        except AuthenticationError:
            raise
        except Exception as e:
            self.logger.error("登录失败", username=username, error=str(e))
            raise AuthenticationError(f"登录失败: {str(e)}")

    async def refresh_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """
        刷新访问令牌

        Args:
            refresh_token: 刷新令牌

        Returns:
            dict: 包含新的 access_token 和 refresh_token 的字典

        Raises:
            AuthenticationError: 刷新令牌无效
        """
        # 定义获取用户信息的回调函数，用于验证用户状态
        async def _get_user_info(uid: int):
            user = await self.user_repository.get_user_by_id(uid, use_cache=False)
            if user:
                role_code = user.role.code if user.role else None
                return {
                    "id": user.id,
                    "email": user.email,
                    "role_code": role_code,
                    "is_admin": role_code == "admin",
                    "status": user.status,
                }
            return None

        result = await AuthService.refresh_access_token(refresh_token, get_user_func=_get_user_info)
        if not result:
            raise AuthenticationError("刷新令牌无效或已过期")

        new_access_token, new_refresh_token, user_id = result

        self.logger.info("Token 刷新成功", user_id=user_id)

        config = get_config()
        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "expires_in": config.security.access_token_expire_minutes * 60,
        }

    async def logout(self, token: str) -> bool:
        """
        用户登出，撤销令牌

        Args:
            token: Access token 或 Refresh token

        Returns:
            bool: 是否成功
        """
        success = await AuthService.logout(token)
        if success:
            self.logger.info("用户登出成功")
        return success

    async def update_user(self, user_id: int, user_update: UserUpdate) -> Optional[UserModel]:
        """
        更新用户信息
        Args:
            user_id: 用户ID
            user_update: 用户更新数据（Pydantic 模型）

        Returns:
            User: 更新后的用户对象，如果用户不存在则返回None
        Raises:
            UserNotFoundError: 如果用户不存在
            UserAlreadyExistsError: 如果新用户名/邮箱/手机号已被占用
        """
        update_data = user_update.model_dump(exclude_unset=True)

        # 唯一性检查：如果更新了用户名、邮箱或手机号，检查是否已被占用（包含软删除用户）
        if "username" in update_data:
            existing = await self.user_repository.get_user_by_username(update_data["username"], use_cache=False, include_deleted=True)
            if existing and existing.id != user_id:
                raise UserAlreadyExistsError(f"用户名 {update_data['username']} 已存在", field="username")
        if "email" in update_data:
            existing = await self.user_repository.get_user_by_email(update_data["email"], use_cache=False, include_deleted=True)
            if existing and existing.id != user_id:
                raise UserAlreadyExistsError(f"邮箱 {update_data['email']} 已被注册", field="email")
        if "phone" in update_data and update_data.get("phone"):
            existing = await self.user_repository.get_user_by_phone(update_data["phone"], include_deleted=True)
            if existing and existing.id != user_id:
                raise UserAlreadyExistsError(f"手机号 {update_data['phone']} 已被注册", field="phone")

        # 安全规则：普通 update_user 接口不允许修改角色（role_code / is_admin 均不接受）
        # 角色分配由 Task 8 专用 PUT /users/{id}/role 端点经 repository 直写，不经此处 schema
        if "role_code" in update_data or "is_admin" in update_data:
            from novamind.features.user.exceptions import PermissionDeniedError
            raise PermissionDeniedError(message="角色字段请使用专用角色分配端点修改")

        # 密码哈希在 Service 层处理（不在 Repository 层）
        password_changed = False
        if "password" in update_data and update_data["password"]:
            from novamind.core.auth.hashing import get_password_hash_async
            user_update.password = await get_password_hash_async(update_data["password"])
            password_changed = True

        user = await self.user_repository.update_user(user_id, user_update)
        if not user:
            raise UserNotFoundError(user_id=user_id)

        # 密码被修改时：旧 token 全部失效 + 清除强制改密标记，与其他改密路径语义一致
        if password_changed:
            await self._apply_password_changed_effects(user_id)

        return user

    async def _apply_password_changed_effects(self, user_id: int) -> None:
        """密码变更后的联动处理：清除强制改密标记 + 拉黑该用户所有 token。"""
        from sqlalchemy import update as sa_update
        async with self.user_repository.db.begin_nested():
            stmt = sa_update(UserModel).where(UserModel.id == user_id).values(must_change_password=False)
            await self.user_repository.db.execute(stmt)
        await AuthService.blacklist_all_user_tokens(user_id)

    async def toggle_user_status(self, user_id: int) -> tuple[bool, int]:
        """
        切换用户状态（ACTIVE ↔ INACTIVE）
        Args:
            user_id: 用户ID

        Returns:
            tuple[bool, int]: (操作是否成功, 新状态值)
        """
        try:
            success, new_status = await self.user_repository.toggle_user_status(user_id)
            if success:
                status_text = "停用" if new_status == UserStatus.INACTIVE else "激活"
                # 停用时将用户所有 Token 纳入黑名单，激活时清除黑名单
                if new_status == UserStatus.INACTIVE:
                    await AuthService.blacklist_all_user_tokens(user_id)
                else:
                    await AuthService.clear_user_blacklist(user_id)
                self.logger.info("用户状态切换成功", user_id=user_id, new_status=new_status, status_text=status_text)
            return success, new_status
        except UserError:
            raise
        except Exception as e:
            self.logger.error("切换用户状态失败", user_id=user_id, error=str(e))
            raise UserOperationError(f"切换用户状态失败: {str(e)}")

    async def soft_delete_user(self, user_id: int) -> bool:
        """
        软删除用户账户
        Args:
            user_id: 用户ID

        Returns:
            bool: 如果成功删除返回True，如果用户不存在返回False
        """
        try:
            success = await self.user_repository.soft_delete(user_id)
            if success:
                # 将用户所有 Token 纳入黑名单，使其立即失效
                await AuthService.blacklist_all_user_tokens(user_id)
                self.logger.info("用户软删除成功", user_id=user_id)
            return success
        except UserError:
            raise
        except Exception as e:
            self.logger.error("软删除用户失败", user_id=user_id, error=str(e))
            raise UserOperationError(f"软删除用户失败: {str(e)}")

    async def check_user_exists(self, username: str) -> bool:
        """
        检查用户是否存在
        Args:
            username: 用户名

        Returns:
            bool: 如果用户存在返回True，否则返回False
        """
        try:
            user = await self.user_repository.get_user_by_username(username, use_cache=False, include_deleted=True)
            exists = user is not None
            return exists
        except UserError:
            raise
        except Exception as e:
            self.logger.error("检查用户是否存在失败", username=username, error=str(e))
            raise UserOperationError(f"检查用户是否存在失败: {str(e)}")

    async def admin_reset_password(self, user_id: int) -> tuple[str, int]:
        """
        管理员重置用户密码，生成临时密码

        Args:
            user_id: 用户 ID

        Returns:
            (临时密码, user_id)

        Raises:
            UserNotFoundError: 用户不存在
        """
        import secrets
        from novamind.core.auth.hashing import get_password_hash_async

        user = await self.user_repository.get_user_by_id(user_id, use_cache=False)
        if not user:
            raise UserNotFoundError(f"用户 {user_id} 不存在")

        # 生成 16 位临时密码
        temp_password = secrets.token_urlsafe(12)
        hashed = await get_password_hash_async(temp_password)

        # 直写密码哈希并设置强制改密标记（不经过 UserUpdate 请求模型——
        # 其 password 字段 max_length=30 + 强度校验针对明文口令，会拒绝 97 字符的 argon2 哈希）
        await self._set_password_hash(user_id, hashed)
        await self._set_must_change_password(user_id, True)

        # 黑名单所有 Token，强制重新登录
        await AuthService.blacklist_all_user_tokens(user_id)

        self.logger.info("管理员已重置用户密码", user_id=user_id)
        return temp_password, user_id

    async def _set_password_hash(self, user_id: int, hashed_password: str) -> None:
        """直写密码哈希列（内部路径，绕过请求 schema 的明文口令校验）。"""
        async with self.user_repository.db.begin_nested():
            stmt = update(UserModel).where(UserModel.id == user_id).values(password_hash=hashed_password)
            await self.user_repository.db.execute(stmt)
        await self.user_repository._invalidate_user_cache(user_id)

    async def _set_must_change_password(self, user_id: int, value: bool) -> None:
        """直写强制改密标记（内部路径，绕过 update_user 字段白名单）。"""
        async with self.user_repository.db.begin_nested():
            stmt = update(UserModel).where(UserModel.id == user_id).values(must_change_password=value)
            await self.user_repository.db.execute(stmt)

    async def change_password(
        self, user_id: int, old_password: str, new_password: str
    ) -> bool:
        """
        用户修改密码

        Args:
            user_id: 用户 ID
            old_password: 当前密码
            new_password: 新密码

        Returns:
            是否修改成功

        Raises:
            AuthenticationError: 当前密码错误
            UserNotFoundError: 用户不存在
        """
        from novamind.core.auth.hashing import verify_password_async, get_password_hash_async

        user = await self.user_repository.get_user_by_id(user_id, use_cache=False)
        if not user:
            raise UserNotFoundError(f"用户 {user_id} 不存在")

        # 验证旧密码
        if not await verify_password_async(old_password, user.password_hash):
            raise AuthenticationError("当前密码错误")

        # 哈希新密码并直写（不经 UserUpdate 请求模型，理由同 admin_reset_password）
        hashed = await get_password_hash_async(new_password)
        await self._set_password_hash(user_id, hashed)

        # 清除强制改密标记 + 黑名单所有 Token，强制重新登录
        await self._set_must_change_password(user_id, False)
        await AuthService.blacklist_all_user_tokens(user_id)

        self.logger.info("用户已修改密码", user_id=user_id)
        return True

    async def reset_password_by_token(self, token: str, new_password: str) -> int:
        """
        通过重置 Token 设置新密码（忘记密码流程）

        业务逻辑归 Service 层：Token 验证、密码落库、一次性失效、强制重新登录。

        Args:
            token: 重置 Token
            new_password: 新密码（明文，强度已在请求 schema 校验）

        Returns:
            user_id: 重置成功的用户 ID

        Raises:
            AuthenticationError: Token 无效或已过期
            UserNotFoundError: 用户不存在
        """
        user_id = await AuthService.verify_reset_token(token)
        if user_id is None:
            raise AuthenticationError("重置链接无效或已过期")

        user = await self.user_repository.get_user_by_id(user_id, use_cache=False)
        if not user:
            raise UserNotFoundError(f"用户 {user_id} 不存在")

        from novamind.core.auth.hashing import get_password_hash_async
        hashed = await get_password_hash_async(new_password)
        await self._set_password_hash(user_id, hashed)

        # 使 Token 失效（一次性使用）
        await AuthService.invalidate_reset_token(token)

        # 黑名单所有 Token，强制重新登录
        await AuthService.blacklist_all_user_tokens(user_id)

        self.logger.info("用户通过重置链接修改密码", user_id=user_id)
        return user_id
