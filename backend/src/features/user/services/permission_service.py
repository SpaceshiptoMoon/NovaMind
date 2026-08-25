"""PermissionService：RBAC 权限查询实现。"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.authorization.ports import PermissionCheckerPort
from novamind.features.user.models.role import Role
from novamind.features.user.models.user import User

ROLE_PERM_CACHE_PREFIX = "rbac:user_perms:"  # Redis key 前缀
ROLE_PERM_TTL = 300  # 5 分钟


class PermissionService(PermissionCheckerPort):
    """基于 ``User -> Role -> Permission`` 的权限查询服务。

    支持 Redis 缓存；未提供 Redis 客户端时直接查询数据库，便于测试与降级。
    """

    def __init__(self, db: AsyncSession, redis_client=None):
        self.db = db
        self.redis = redis_client

    async def get_user_permissions(self, user_id: int) -> set[str]:
        # 1. Redis 缓存
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
                f"{ROLE_PERM_CACHE_PREFIX}{user_id}", ",".join(perms), ex=ROLE_PERM_TTL
            )
        return perms

    async def invalidate(self, user_id: int) -> None:
        if self.redis:
            await self.redis.delete(f"{ROLE_PERM_CACHE_PREFIX}{user_id}")
