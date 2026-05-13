from typing import Optional, List, Dict, Any

from src.core.middleware.structured_logging import get_logger
from src.features.user.models.user import User as UserModel, UserStatus
from src.features.user.schemas.user_schema import UserUpdate
from src.features.user.repository.user_repository import UserRepository
from src.features.user.api.exceptions import (
    UserAlreadyExistsError,
    UserNotFoundError,
    UserCreationError,
    UserOperationError,
    AuthenticationError,
    UserError,
)
from src.features.user.services.auth_service import AuthService
from src.setting.yaml_config import get_config


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
        is_admin: bool = False,
    ) -> Optional[UserModel]:
        """
        创建新用户
        Args:
            username: 用户名
            email: 邮箱
            password: 密码
            phone: 电话号码（可选）
            status: 用户状态（可选，默认为1）
            is_admin: 是否管理员（可选，默认为 False）

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

            # 创建新用户（密码哈希在 Service 层处理）
            from src.core.auth.hashing import get_password_hash_async
            user_create = {
                "username": username,
                "email": email,
                "password": await get_password_hash_async(password),
                "phone": phone,
                "status": status,
                "is_admin": is_admin,
            }
            user = await self.user_repository.create_user(user_create)
            # 记录用户创建成功（关键业务事件）
            self.logger.info("用户创建成功", user_id=user.id)
            return user
        except UserAlreadyExistsError:
            # 用户已存在，直接重新抛出异常
            raise
        except Exception as e:
            self.logger.error("创建用户失败", error=str(e))
            raise UserCreationError(f"创建用户失败: {str(e)}")

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
                access_token, refresh_token = await AuthService.create_token_pair(
                    user_id=user.id,
                    username=user.username,
                    email=user.email,
                    is_admin=user.is_admin,
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
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "is_admin": user.is_admin,
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
                return {
                    "id": user.id,
                    "email": user.email,
                    "is_admin": user.is_admin,
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

        # 密码哈希在 Service 层处理（不在 Repository 层）
        if "password" in update_data and update_data["password"]:
            from src.core.auth.hashing import get_password_hash_async
            user_update.password = await get_password_hash_async(update_data["password"])

        user = await self.user_repository.update_user(user_id, user_update)
        if not user:
            raise UserNotFoundError(user_id=user_id)
        return user

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
