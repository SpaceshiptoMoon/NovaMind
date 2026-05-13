"""
用户仓储

处理用户的数据访问操作
支持 Redis 缓存
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from typing import Optional, Dict, Any

from src.features.user.models.user import User, UserStatus
from src.features.user.schemas.user_schema import UserUpdate
from src.core.auth.hashing import verify_password_async
from src.shared.cache.redis_client import get_redis_client
from src.core.middleware.structured_logging import get_logger


# 缓存 TTL 常量
USER_CACHE_TTL = 7200  # 2 小时

logger = get_logger(__name__)


class UserRepository:
    # 允许通过 update_user 更新的字段白名单
    _UPDATABLE_FIELDS = frozenset({
        "username", "email", "phone", "is_admin", "status",
    })

    def __init__(self, db: AsyncSession = None):
        self.db = db
        self._cache = None

    async def _get_cache(self):
        """获取 Redis 缓存客户端"""
        if self._cache is None:
            self._cache = await get_redis_client()
        return self._cache

    def _get_user_cache_key(self, user_id: int) -> str:
        """生成用户 ID 缓存键"""
        return f"user:id:{user_id}"

    def _get_username_cache_key(self, username: str) -> str:
        """生成用户名缓存键"""
        return f"user:name:{username}"

    async def _cache_user(self, user: User) -> None:
        """缓存用户信息"""
        try:
            cache = await self._get_cache()
            user_data = {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "phone": user.phone,
                "is_admin": user.is_admin,
                "status": user.status,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }
            # 缓存 ID 索引
            await cache.set(self._get_user_cache_key(user.id), user_data, expire=USER_CACHE_TTL)
            # 缓存用户名索引
            await cache.set(self._get_username_cache_key(user.username), {"id": user.id}, expire=USER_CACHE_TTL)
        except Exception as e:
            logger.warning("缓存用户信息失败", user_id=user.id, error=str(e))

    async def _invalidate_user_cache(self, user_id: int, username: str = None) -> None:
        """失效用户缓存"""
        try:
            cache = await self._get_cache()
            await cache.delete(self._get_user_cache_key(user_id))
            if username:
                await cache.delete(self._get_username_cache_key(username))
            logger.debug("用户缓存已失效", user_id=user_id)
        except Exception as e:
            logger.warning("失效用户缓存失败", user_id=user_id, error=str(e))

    async def create_user(self, user_create: dict) -> User:
        """
        创建新用户

        Args:
            user_create: 用户创建数据字典

        Returns:
            User: 新创建的用户对象

        Raises:
            ValueError: 数据库会话未设置或用户名/邮箱已存在
        """
        if not self.db:
            raise ValueError("数据库会话未设置")

        hashed_password = user_create["password"]  # 密码已在 Service 层完成哈希
        new_user = User(
            username=user_create["username"],
            email=user_create["email"],
            phone=user_create.get("phone"),
            password_hash=hashed_password,
            is_admin=user_create.get("is_admin", False),
            status=user_create.get("status", UserStatus.ACTIVE),
        )
        try:
            # 使用嵌套事务（SAVEPOINT），支持外部已有事务的情况
            async with self.db.begin_nested():
                self.db.add(new_user)
                await self.db.flush()  # 获取自增 ID 但不提交
                await self.db.refresh(new_user)
            # 注意：不在此处 commit，由调用方统一管理事务
            # 这允许调用方在多个操作后统一提交或回滚
            return new_user
        except IntegrityError:
            # 嵌套事务会自动回滚 SAVEPOINT，无需手动 rollback
            raise ValueError("用户名或邮箱已被注册")

    async def get_user_by_username(self, username: str, use_cache: bool = True, include_deleted: bool = False) -> Optional[User]:
        """根据用户名获取用户（带缓存）

        Args:
            username: 用户名
            use_cache: 是否使用缓存
            include_deleted: 是否包含已软删除的用户（用于唯一性检查）
        """
        if not self.db:
            raise ValueError("数据库会话未设置")

        # include_deleted=True 时跳过缓存（缓存只存活跃用户）
        # 尝试从缓存获取
        if use_cache and not include_deleted:
            try:
                cache = await self._get_cache()
                username_cache_key = self._get_username_cache_key(username)
                cached_id = await cache.get(username_cache_key)

                if cached_id is not None:
                    # 通过 ID 缓存获取完整用户信息
                    user_id = cached_id.get("id")
                    if user_id:
                        user_cache_key = self._get_user_cache_key(user_id)
                        cached_user = await cache.get(user_cache_key)
                        if cached_user is not None:
                            logger.debug("用户缓存命中", username=username, user_id=user_id)
                            # 使用 session.get() 优先从 identity map 获取，减少 DB 查询
                            user = await self.db.get(User, user_id)
                            if user is None:
                                return None
                            # 刷新对象以确保获取数据库最新状态，
                            # 避免 expire_on_commit=False 下 identity map 持有过期数据
                            await self.db.refresh(user)
                            if user.deleted_at is not None or user.status == UserStatus.DELETED:
                                return None
                            return user
            except Exception as e:
                logger.warning("读取用户缓存失败", username=username, error=str(e))

        # 从数据库获取
        conditions = [User.username == username]
        if not include_deleted:
            conditions.append(User.deleted_at.is_(None))
        stmt = select(User).where(*conditions)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        # 缓存结果（仅活跃用户）
        if user and use_cache and not include_deleted:
            await self._cache_user(user)

        return user

    async def get_user_by_id(self, user_id: int, use_cache: bool = True) -> Optional[User]:
        """根据用户ID获取用户（带缓存）"""
        if not self.db:
            raise ValueError("数据库会话未设置")

        # 尝试从缓存获取
        if use_cache:
            try:
                cache = await self._get_cache()
                cache_key = self._get_user_cache_key(user_id)
                cached_user = await cache.get(cache_key)

                if cached_user is not None:
                    logger.debug("用户缓存命中", user_id=user_id)
                    # 使用 session.get() 优先从 identity map 获取，减少 DB 查询
                    user = await self.db.get(User, user_id)
                    if user is None:
                        return None
                    # 刷新对象以确保获取数据库最新状态，
                    # 避免 expire_on_commit=False 下 identity map 持有过期数据
                    await self.db.refresh(user)
                    if user.deleted_at is not None or user.status == UserStatus.DELETED:
                        return None
                    return user
            except Exception as e:
                logger.warning("读取用户缓存失败", user_id=user_id, error=str(e))

        # 从数据库获取
        stmt = select(User).where(
            User.id == user_id,
            User.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        # 缓存结果
        if user and use_cache:
            await self._cache_user(user)

        return user

    async def get_users(self, skip: int = 0, limit: int = 100) -> list[User]:
        """获取用户列表（排除已删除用户）"""
        if not self.db:
            raise ValueError("数据库会话未设置")
        stmt = select(User).where(
            User.status != UserStatus.DELETED,
            User.deleted_at.is_(None),
        ).offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def update_user(
        self, user_id: int, user_update: UserUpdate
    ) -> Optional[User]:
        """
        更新用户信息（同时失效缓存）

        Args:
            user_id: 用户ID
            user_update: 用户更新数据

        Returns:
            Optional[User]: 更新后的用户对象，用户不存在时返回 None
        """
        if not self.db:
            raise ValueError("数据库会话未设置")

        # 先获取用户（不使用缓存，确保获取最新数据）
        db_user = await self.get_user_by_id(user_id, use_cache=False)
        if not db_user:
            return None

        old_username = db_user.username

        update_data = user_update.model_dump(exclude_unset=True)

        # 构建更新字段字典（仅允许白名单内的字段）
        values_to_update = {}
        for field, value in update_data.items():
            # password 是特殊字段，映射到 User.password_hash
            if field == "password" and value:
                values_to_update["password_hash"] = value  # 密码已在 Service 层完成哈希
            elif field in self._UPDATABLE_FIELDS and hasattr(User, field):
                values_to_update[field] = value

        if values_to_update:
            # 使用嵌套事务（支持外部已有事务的情况）
            async with self.db.begin_nested():
                stmt = update(User).where(User.id == user_id).values(**values_to_update)
                await self.db.execute(stmt)
            # 注意：不在此处 commit，由调用方统一管理事务

        # 失效缓存
        await self._invalidate_user_cache(user_id, old_username)

        # 重新获取更新后的用户（不使用缓存）
        return await self.get_user_by_id(user_id, use_cache=False)

    async def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """
        验证用户身份

        只有 status == ACTIVE 的用户才能登录
        """
        if not self.db:
            raise ValueError("数据库会话未设置")

        user = await self.get_user_by_username(username)
        if not user or not await verify_password_async(password, user.password_hash):
            return None

        # 只有 ACTIVE 状态的用户才能登录
        if user.status != UserStatus.ACTIVE:
            return None

        return user

    async def toggle_user_status(self, user_id: int) -> tuple[bool, int]:
        """
        切换用户状态（ACTIVE ↔ INACTIVE）

        Args:
            user_id: 用户ID

        Returns:
            tuple[bool, int]: (操作是否成功, 新状态值)
        """
        if not self.db:
            raise ValueError("数据库会话未设置")

        # 先查询当前状态
        user = await self.get_user_by_id(user_id)
        if not user:
            return False, 0

        # 仅允许 ACTIVE <-> INACTIVE 切换，BANNED/DELETED 状态不允许通过此接口切换
        if user.status not in (UserStatus.ACTIVE, UserStatus.INACTIVE):
            return False, user.status

        # 切换状态
        new_status = UserStatus.INACTIVE if user.status == UserStatus.ACTIVE else UserStatus.ACTIVE

        async with self.db.begin_nested():
            stmt = (
                update(User)
                .where(User.id == user_id)
                .values(status=new_status)
            )
            result = await self.db.execute(stmt)
        # 注意：不在此处 commit，由调用方统一管理事务

        # 失效用户缓存，确保状态变更立即生效
        if result.rowcount > 0:
            await self._invalidate_user_cache(user_id, user.username)

        return result.rowcount > 0, new_status

    async def get_user_by_phone(self, phone: str, include_deleted: bool = False) -> Optional[User]:
        """
        根据手机号获取用户（排除已删除用户）

        Args:
            phone: 手机号
            include_deleted: 是否包含已软删除的用户（用于唯一性检查）

        Returns:
            用户对象或 None
        """
        if not self.db:
            raise ValueError("数据库会话未设置")

        conditions = [User.phone == phone]
        if not include_deleted:
            conditions.append(User.deleted_at.is_(None))
        stmt = select(User).where(*conditions)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str, use_cache: bool = True, include_deleted: bool = False) -> Optional[User]:
        """
        根据邮箱获取用户（排除已删除用户）

        Args:
            email: 用户邮箱
            use_cache: 是否使用缓存
            include_deleted: 是否包含已软删除的用户（用于唯一性检查）

        Returns:
            用户对象或 None
        """
        if not self.db:
            raise ValueError("数据库会话未设置")

        conditions = [User.email == email]
        if not include_deleted:
            conditions.append(User.deleted_at.is_(None))
        stmt = select(User).where(*conditions)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        # 缓存结果（仅活跃用户）
        if user and use_cache and not include_deleted:
            await self._cache_user(user)

        return user

    async def soft_delete(self, user_id: int) -> bool:
        """
        软删除用户

        Args:
            user_id: 用户ID

        Returns:
            bool: 软删除成功返回 True，用户不存在返回 False
        """
        if not self.db:
            raise ValueError("数据库会话未设置")

        # 获取用户
        user = await self.get_user_by_id(user_id, use_cache=False)
        if not user:
            return False

        # 调用模型的软删除方法
        user.soft_delete()

        async with self.db.begin_nested():
            self.db.add(user)
        # 注意：不在此处 commit，由调用方统一管理事务

        # 失效缓存
        await self._invalidate_user_cache(user_id, user.username)

        return True

    async def update_login_info(self, user_id: int, ip_address: str) -> bool:
        """
        更新用户登录信息（最后登录时间、IP、登录次数）

        Args:
            user_id: 用户ID
            ip_address: 登录IP地址

        Returns:
            bool: 更新成功返回 True，用户不存在返回 False
        """
        if not self.db:
            raise ValueError("数据库会话未设置")

        # 获取用户
        user = await self.get_user_by_id(user_id, use_cache=False)
        if not user:
            return False

        # 更新登录信息
        user.update_login_info(ip_address)

        async with self.db.begin_nested():
            self.db.add(user)
        # 注意：不在此处 commit，由调用方统一管理事务

        # 失效缓存
        await self._invalidate_user_cache(user_id, user.username)

        return True
