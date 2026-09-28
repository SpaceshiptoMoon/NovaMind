"""用户搜索配置仓储；写操作一律 begin_nested()（SAVEPOINT）。"""

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.user.models.user_search_config import UserSearchConfig
from novamind.features.user.schemas.search_config_schema import (
    SearchConfigCreate,
    SearchConfigUpdate,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class SearchConfigRepository:
    """用户搜索配置仓储"""

    def __init__(self, db: AsyncSession):
        """绑定请求级数据库会话。"""
        self.db = db

    # ========== 基础查询 ==========

    async def get_by_id(self, config_id: int) -> UserSearchConfig | None:
        """根据配置 ID 获取（不限定用户，由 service 层校验归属）。

        Args:
            config_id: 配置 ID。

        Returns:
            搜索配置记录，不存在返回 None。
        """
        stmt = select(UserSearchConfig).where(UserSearchConfig.id == config_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user_and_provider(
        self,
        user_id: int,
        provider: str,
    ) -> UserSearchConfig | None:
        """获取用户指定 provider 的配置（唯一性检查用）。

        Args:
            user_id: 用户 ID。
            provider: 搜索服务商名（内部统一小写比较）。

        Returns:
            配置记录，无则 None。
        """
        stmt = select(UserSearchConfig).where(
            UserSearchConfig.user_id == user_id,
            UserSearchConfig.provider == provider.lower(),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_primary(self, user_id: int) -> UserSearchConfig | None:
        """获取用户首选搜索配置（is_primary=True）。

        Args:
            user_id: 用户 ID。

        Returns:
            首选配置记录，未设置返回 None。
        """
        stmt = select(UserSearchConfig).where(
            UserSearchConfig.user_id == user_id,
            UserSearchConfig.is_primary.is_(True),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int) -> list[UserSearchConfig]:
        """获取用户的搜索配置列表（按创建时间倒序）。

        Args:
            user_id: 用户 ID。

        Returns:
            配置列表。
        """
        stmt = select(UserSearchConfig).where(
            UserSearchConfig.user_id == user_id
        ).order_by(UserSearchConfig.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_user(self, user_id: int) -> int:
        """统计用户搜索配置数量。

        Args:
            user_id: 用户 ID。

        Returns:
            配置数量。
        """
        stmt = select(func.count(UserSearchConfig.id)).where(
            UserSearchConfig.user_id == user_id
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    # ========== 创建/更新/删除 ==========

    async def create(
        self,
        user_id: int,
        data: SearchConfigCreate,
    ) -> UserSearchConfig:
        """创建搜索配置（SAVEPOINT 包裹，不提交，由外层事务统一管理）。

        Args:
            user_id: 归属用户 ID。
            data: 创建数据（provider/api_key/extra_config/is_primary）。

        Returns:
            创建后的配置记录（api_key 已是调用方加密后的密文）。
        """
        config = UserSearchConfig(
            user_id=user_id,
            provider=data.provider,
            api_key=data.api_key,
            extra_config=data.extra_config,
            is_primary=data.is_primary,
        )
        async with self.db.begin_nested():
            self.db.add(config)
            await self.db.flush()  # 获取自增 ID 但不提交
            await self.db.refresh(config)
        return config

    async def update(
        self,
        config: UserSearchConfig,
        data: SearchConfigUpdate,
    ) -> UserSearchConfig:
        """更新搜索配置（仅写入 exclude_unset 的字段，SAVEPOINT 包裹）。

        Args:
            config: 待更新的 ORM 配置对象。
            data: 更新数据（仅显式传入的字段生效；api_key 为调用方加密后密文）。

        Returns:
            刷新后的配置记录。
        """
        update_data = data.model_dump(exclude_unset=True)
        async with self.db.begin_nested():
            for field, value in update_data.items():
                setattr(config, field, value)
            await self.db.flush()
            await self.db.refresh(config)
        return config

    async def delete(self, config_id: int) -> bool:
        """删除配置（SAVEPOINT 包裹）

        Returns:
            删除成功返回 True，配置不存在返回 False
        """
        async with self.db.begin_nested():
            stmt = delete(UserSearchConfig).where(UserSearchConfig.id == config_id)
            result = await self.db.execute(stmt)
            await self.db.flush()
            return result.rowcount > 0

    async def clear_primary(self, user_id: int) -> int:
        """清除用户所有 is_primary=True 标记（设新 primary 前调用，SAVEPOINT 包裹）

        Returns:
            受影响行数
        """
        async with self.db.begin_nested():
            stmt = (
                update(UserSearchConfig)
                .where(
                    UserSearchConfig.user_id == user_id,
                    UserSearchConfig.is_primary.is_(True),
                )
                .values(is_primary=False)
            )
            result = await self.db.execute(stmt)
            await self.db.flush()
            return result.rowcount

    async def set_primary(self, user_id: int, config_id: int) -> UserSearchConfig | None:
        """原子切换用户首选：先清所有 is_primary，再设目标为 primary（单个 SAVEPOINT）。

        目标不存在或不属于该用户返回 None（由 service 层抛 NotFound）。
        """
        async with self.db.begin_nested():
            # 清旧 primary
            await self.db.execute(
                update(UserSearchConfig)
                .where(
                    UserSearchConfig.user_id == user_id,
                    UserSearchConfig.is_primary.is_(True),
                )
                .values(is_primary=False)
            )
            # 设新 primary
            config = await self.db.get(UserSearchConfig, config_id)
            if config is None or config.user_id != user_id:
                return None
            config.is_primary = True
            await self.db.flush()
            await self.db.refresh(config)
            return config