"""AppAccessService：用户应用级权限（deny-list，无记录=可用）查询与全量替换；缓存键与 RbacPermissionService 互相独立。"""
from __future__ import annotations

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.user.models.user_disabled_app import UserDisabledApp
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

APPGATE_CACHE_PREFIX = "appgate:disabled:"  # Redis key 前缀
APPGATE_TTL = 300  # 5 分钟（与 RBAC 权限缓存对齐）


class AppAccessService:
    """应用禁用查询/替换服务（Redis 缓存，未装配 Redis 时直查 DB）。"""

    def __init__(self, db: AsyncSession, redis_client=None):
        """绑定数据库会话与可选 Redis 客户端（未装配时降级直查 DB）。"""
        self.db = db
        self.redis = redis_client
        self.logger = get_logger(__name__)

    @classmethod
    async def with_redis(cls, db: AsyncSession) -> AppAccessService:
        """装配点便捷构造：自取 Redis 单例（失败降级 None 走 DB 直查）。

        Args:
            db: 请求级数据库会话。

        Returns:
            AppAccessService 实例。
        """
        try:
            from novamind.shared.storage.client_factory import ClientFactory

            redis_client = await ClientFactory.get_redis_client()
        except Exception:
            redis_client = None
        return cls(db, redis_client)

    # ==================== 查询 ====================

    async def get_disabled_apps(self, user_id: int) -> set[str]:
        """用户被禁用的应用集合（空集 = 全部可用）。

        Args:
            user_id: 用户 ID。

        Returns:
            被禁用的应用代码集合（优先 Redis 缓存，空集也会缓存）。
        """
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
        """门禁判定入口（AppGateMiddleware 调用）。

        Args:
            user_id: 用户 ID。
            app_code: 应用代码。

        Returns:
            该应用对该用户已被禁用返回 True。
        """
        return app_code in await self.get_disabled_apps(user_id)

    # ==================== 替换（管理端点） ====================

    async def set_disabled_apps(
        self,
        user_id: int,
        app_codes: set[str],
        operator_id: int | None = None,
    ) -> None:
        """全量替换用户的禁用应用集合（delete + insert，单个 SAVEPOINT）。

        Args:
            user_id: 用户 ID。
            app_codes: 新的禁用应用代码集合；空集表示全部可用。
            operator_id: 操作管理员用户 ID，用于审计；可为 None。
        """
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
        """失效用户的应用门禁缓存（Redis 未装配时静默跳过）。

        Args:
            user_id: 用户 ID。
        """
        if self.redis:
            await self.redis.delete(f"{APPGATE_CACHE_PREFIX}{user_id}")
