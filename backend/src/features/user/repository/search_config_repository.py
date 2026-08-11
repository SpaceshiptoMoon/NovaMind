"""
用户搜索配置仓储

处理用户搜索配置的数据访问操作，每条配置绑定具体用户。

**写操作一律用 ``async with self.db.begin_nested():`` 包裹（SAVEPOINT）**，遵守
``docs/transaction-boundary-conventions.md`` 铁律——``model_config_repository`` 未用
SAVEPOINT 是历史偏离特例，不照抄。
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update, func
from typing import Optional, List

from novamind.features.user.models.user_search_config import UserSearchConfig
from novamind.features.user.schemas.search_config_schema import (
    SearchConfigCreate,
    SearchConfigUpdate,
)
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class SearchConfigRepository:
    """用户搜索配置仓储"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========== 基础查询 ==========

    async def get_by_id(self, config_id: int) -> Optional[UserSearchConfig]:
        """根据配置 ID 获取（不限定用户，由 service 层校验归属）"""
        stmt = select(UserSearchConfig).where(UserSearchConfig.id == config_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user_and_provider(
        self,
        user_id: int,
        provider: str,
    ) -> Optional[UserSearchConfig]:
        """获取用户指定 provider 的配置（唯一性检查用）"""
        stmt = select(UserSearchConfig).where(
            UserSearchConfig.user_id == user_id,
            UserSearchConfig.provider == provider.lower(),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_primary(self, user_id: int) -> Optional[UserSearchConfig]:
        """获取用户首选搜索配置（is_primary=True）"""
        stmt = select(UserSearchConfig).where(
            UserSearchConfig.user_id == user_id,
            UserSearchConfig.is_primary.is_(True),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int) -> List[UserSearchConfig]:
        """获取用户的搜索配置列表（按创建时间倒序）"""
        stmt = select(UserSearchConfig).where(
            UserSearchConfig.user_id == user_id
        ).order_by(UserSearchConfig.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_user(self, user_id: int) -> int:
        """统计用户搜索配置数量"""
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
        """创建搜索配置（SAVEPOINT 包裹，不提交，由外层事务统一管理）"""
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
        """更新搜索配置（仅写入 exclude_unset 的字段，SAVEPOINT 包裹）"""
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

    async def set_primary(self, user_id: int, config_id: int) -> Optional[UserSearchConfig]:
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