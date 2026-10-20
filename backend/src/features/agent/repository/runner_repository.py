"""伴生 runner 设备 repository：设备 CRUD 与状态更新（flush 不 commit）。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.agent.models.runner import RunnerDevice


class RunnerDeviceRepository:
    """runner_devices 表访问（写操作遵循 begin_nested 约定由 service 层收口）"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_device_key_hash(self, key_hash: str) -> RunnerDevice | None:
        """按 device_key 哈希查设备（WS 握手认证路径）。"""
        result = await self.session.execute(
            select(RunnerDevice).where(RunnerDevice.device_key_hash == key_hash)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int) -> list[RunnerDevice]:
        """列出用户全部设备（created_at 倒序，含 revoked 供审计展示）。"""
        result = await self.session.execute(
            select(RunnerDevice)
            .where(RunnerDevice.user_id == user_id)
            .order_by(RunnerDevice.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_owned(self, user_id: int, device_id: int) -> RunnerDevice | None:
        """按 id 查设备并校验属主（重命名/吊销路径）。"""
        result = await self.session.execute(
            select(RunnerDevice).where(
                RunnerDevice.id == device_id, RunnerDevice.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def create(self, device: RunnerDevice) -> RunnerDevice:
        """落库新设备并返回刷新后的实体（flush 不 commit）。"""
        self.session.add(device)
        await self.session.flush()
        await self.session.refresh(device)
        return device
