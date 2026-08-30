"""AppAccessService：用户应用级权限（deny-list）查询与替换。

应用门禁的数据面：``user_disabled_apps`` 表只存被禁用的应用（无记录=可用，
默认全开放），管理员经 ``PUT /users/{id}/app-access`` 全量替换。

与 ``RbacPermissionService`` 的区别：后者查平台管理面权限码（user.manage 等），
本类查应用入口可见性（qa/agent/skill/app/clawmate）。缓存模式互相独立
（``appgate:disabled:{uid}`` vs ``rbac:user_perms:{uid}``）。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.user.models.user_disabled_app import UserDisabledApp

APPGATE_CACHE_PREFIX = "appgate:disabled:"  # Redis key 前缀
APPGATE_TTL = 300  # 5 分钟（与 RBAC 权限缓存对齐）


class AppAccessService:
    """应用禁用查询/替换服务（Redis 缓存，未装配 Redis 时直查 DB）。"""

    def __init__(self, db: AsyncSession, redis_client=None):
        self.db = db
        self.redis = redis_client
        self.logger = get_logger(__name__)

    # ==================== 查询 ====================

    async def get_disabled_apps(self, user_id: int) -> set[str]:
        """用户被禁用的应用集合（空集 = 全部可用）。"""
        if self.redis:
            cached = await self.redis.get(f"{APPGATE_CACHE_PREFIX}{user_id}")
            if cached is not None:
                return set(cached.split(",")) if cached else set()

        codes = set(
            (
                await self.db.execute(
                    select(UserDisabledApp.app_code).where(UserDisabledApp.user_id == user_id)
                )
            ).scalars().all()
        )

        # 空集也缓存：禁用表通常接近空，避免每次门禁判定都查库
        if self.redis:
            await self.redis.set(
                f"{APPGATE_CACHE_PREFIX}{user_id}", ",".join(sorted(codes)), expire=APPGATE_TTL
            )
        return codes

    async def is_app_disabled(self, user_id: int, app_code: str) -> bool:
        """门禁判定入口（AppGateMiddleware 调用）。"""
        return app_code in await self.get_disabled_apps(user_id)

    # ==================== 替换（管理端点） ====================

    async def set_disabled_apps(
        self,
        user_id: int,
        app_codes: set[str],
        operator_id: Optional[int] = None,
    ) -> None:
        """全量替换用户的禁用应用集合（delete + insert，单个 SAVEPOINT）。"""
        # SQLite 下 BigInteger 主键不自动分配，手动分配自增 ID
        is_sqlite = self.db.bind is not None and self.db.bind.dialect.name == "sqlite"

        async with self.db.begin_nested():
            await self.db.execute(
                delete(UserDisabledApp).where(UserDisabledApp.user_id == user_id)
            )
            for code in sorted(app_codes):
                row = UserDisabledApp(user_id=user_id, app_code=code, created_by=operator_id)
                if is_sqlite:
                    from sqlalchemy import func

                    max_id = (
                        await self.db.execute(select(func.max(UserDisabledApp.id)))
                    ).scalar()
                    row.id = (max_id or 0) + 1
                self.db.add(row)
            await self.db.flush()

        await self.invalidate(user_id)
        self.logger.info(
            "应用禁用集合已更新", user_id=user_id, disabled=sorted(app_codes), operator_id=operator_id
        )

    # ==================== 缓存 ====================

    async def invalidate(self, user_id: int) -> None:
        if self.redis:
            await self.redis.delete(f"{APPGATE_CACHE_PREFIX}{user_id}")
