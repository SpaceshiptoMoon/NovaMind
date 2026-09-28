"""RbacPermissionService：平台管理面 RBAC 权限码查询（用户→角色→权限码），与空间资源面 SpaceAccessChecker 区分。"""

from novamind.features.user.models.user import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ROLE_PERM_CACHE_PREFIX = "rbac:user_perms:"  # Redis key 前缀
ROLE_PERM_TTL = 300  # 5 分钟


class RbacPermissionService:
    """基于 ``User -> Role -> Permission`` 的权限查询服务。

    支持 Redis 缓存；未提供 Redis 客户端时直接查询数据库，便于测试与降级。
    """

    def __init__(self, db: AsyncSession, redis_client=None):
        """绑定数据库会话与可选 Redis 客户端（未装配时降级直查 DB）。"""
        self.db = db
        self.redis = redis_client

    async def get_user_permissions(self, user_id: int) -> set[str]:
        # 1. Redis 缓存
        """查用户权限码集合：admin 角色直接放行全部，其余按角色映射；结果缓存 5 分钟（空集不缓存）。

        Args:
            user_id: 用户 ID。

        Returns:
            权限码集合；用户不存在或无角色返回空集。
        """
        if self.redis:
            cached = await self.redis.get(f"{ROLE_PERM_CACHE_PREFIX}{user_id}")
            if cached is not None:
                return set(cached.split(",")) if cached else set()

        # 2. 查 DB：user → role → permissions
        user = (
            await self.db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if not user or not user.role:
            return set()

        # admin 角色直接返回全部权限码（等价放行）
        if user.role.code == "admin":
            from novamind.core.authorization.permission_codes import SystemPermission

            perms = set(SystemPermission.ALL)
        else:
            perms = {p.code for p in user.role.permissions}

        # 3. 写缓存（空集合不缓存，避免权限授予/回收后命中旧空缓存）
        if self.redis and perms:
            await self.redis.set(
                f"{ROLE_PERM_CACHE_PREFIX}{user_id}", ",".join(perms), expire=ROLE_PERM_TTL
            )
        return perms

    async def invalidate(self, user_id: int) -> None:
        """失效用户的权限码缓存（Redis 未装配时静默跳过）。

        Args:
            user_id: 用户 ID。
        """
        if self.redis:
            await self.redis.delete(f"{ROLE_PERM_CACHE_PREFIX}{user_id}")
