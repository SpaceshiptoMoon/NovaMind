"""Agent API key 数据访问层。所有写操作走 begin_nested()（SAVEPOINT 硬规则）。"""
from datetime import datetime

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent_api.models.api_key import AgentApiKey, ApiKeyStatus
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class ApiKeyRepository:
    """AgentApiKey 数据访问仓库"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_hash(self, key_hash: str) -> AgentApiKey | None:
        """按 hash 等值查找（唯一索引，鉴权热路径）。"""
        result = await self.session.execute(
            select(AgentApiKey).where(AgentApiKey.key_hash == key_hash)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_user(self, key_id: int, user_id: int) -> AgentApiKey | None:
        """按 id + 归属查（防横探：他人 key 与不存在同样返回 None）。"""
        result = await self.session.execute(
            select(AgentApiKey).where(
                AgentApiKey.id == key_id,
                AgentApiKey.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int) -> list[AgentApiKey]:
        """用户的全部 key（含已吊销——列表页展示历史）。"""
        result = await self.session.execute(
            select(AgentApiKey)
            .where(AgentApiKey.user_id == user_id)
            .order_by(AgentApiKey.id.desc())
        )
        return list(result.scalars().all())

    async def count_by_user(self, user_id: int) -> int:
        """用户有效 key 数量（上限校验用；已吊销不占额）。"""
        from sqlalchemy import func

        result = await self.session.execute(
            select(func.count(AgentApiKey.id)).where(
                AgentApiKey.user_id == user_id,
                AgentApiKey.status == ApiKeyStatus.ACTIVE.value,
            )
        )
        return int(result.scalar() or 0)

    async def create(self, record: AgentApiKey) -> AgentApiKey:
        """插入 key 行。"""
        async with self.session.begin_nested():
            self.session.add(record)
            await self.session.flush()
        await self.session.refresh(record)
        return record

    async def revoke(self, record: AgentApiKey) -> AgentApiKey:
        """吊销（置状态 + 时间戳；幂等性由调用方保证）。"""
        async with self.session.begin_nested():
            record.status = ApiKeyStatus.REVOKED.value
            record.revoked_at = datetime.now()
            await self.session.flush()
        await self.session.refresh(record)
        return record

    async def touch_last_used(self, key_id: int) -> None:
        """更新最近使用时间（fire-and-forget：调用方吞异常，失败不影响鉴权）。"""
        async with self.session.begin_nested():
            await self.session.execute(
                update(AgentApiKey)
                .where(AgentApiKey.id == key_id)
                .values(last_used_at=datetime.now())
            )
