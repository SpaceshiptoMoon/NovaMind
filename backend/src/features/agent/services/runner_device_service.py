"""伴生 runner 设备服务：配对 token 生命周期、设备注册/列表/吊销。

配对 token 存 Redis（一次性、10 分钟 TTL、值含 user_id），消费即删——
换取 device_key 持久凭证。device_key 明文只在配对响应出现一次，
库中只存 SHA-256 哈希（同密码哈希纪律）。
"""
import hashlib
import secrets

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent.exceptions import RunnerDeviceNotFoundError, RunnerPairingError
from novamind.features.agent.models.runner import RunnerDevice
from novamind.features.agent.repository.runner_repository import RunnerDeviceRepository
from novamind.shared.utils.time_utils import now_china
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# 配对 token 的 Redis 键前缀与 TTL（秒）
_PAIRING_KEY_PREFIX = "runner:pairing:"
_PAIRING_TTL_SECONDS = 600


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class RunnerDeviceService:
    """设备配对与管理（P0：无工作区绑定；绑定属 P1）"""

    def __init__(self, db: AsyncSession, redis_client):
        self.db = db
        self.redis = redis_client
        self.repo = RunnerDeviceRepository(db)

    async def create_pairing_token(self, user_id: int) -> str:
        """生成本用户的一次性配对 token（10 分钟有效）。"""
        token = secrets.token_urlsafe(24)
        await self.redis.setex(_PAIRING_KEY_PREFIX + token, _PAIRING_TTL_SECONDS, str(user_id))
        return token

    async def pair(self, pairing_token: str, os_type: str, version: str) -> tuple[RunnerDevice, str]:
        """配对：pairing_token 换设备记录 + device_key（明文仅此一次返回）。

        Raises:
            RunnerPairingError: token 无效/过期/已消费。
        """
        key = _PAIRING_KEY_PREFIX + pairing_token
        user_id_raw = await self.redis.get(key)
        if user_id_raw is None:
            raise RunnerPairingError()
        await self.redis.delete(key)  # 消费即删（一次性）

        device_key = secrets.token_urlsafe(32)
        device = await self.repo.create(
            RunnerDevice(
                user_id=int(user_id_raw),
                name=f"{os_type} 设备",
                device_key_hash=_hash_key(device_key),
                os_type=os_type[:20],
                version=version[:30],
                status="offline",  # 上线由 WS 握手置 online
            )
        )
        logger.info("runner 设备配对成功", device_id=device.id, user_id=device.user_id)
        return device, device_key

    async def authenticate_hello(self, device_key: str) -> RunnerDevice | None:
        """WS hello 认证：按 device_key 哈希查设备，revoked 拒绝。"""
        device = await self.repo.get_by_device_key_hash(_hash_key(device_key))
        if device is None or device.status == "revoked":
            return None
        return device

    async def mark_seen(self, device_id: int, online: bool) -> None:
        """更新设备活跃状态（WS 上线/心跳/断线路径调用，幂等）。"""
        from sqlalchemy import update

        await self.db.execute(
            update(RunnerDevice)
            .where(RunnerDevice.id == device_id)
            .values(status="online" if online else "offline", last_seen_at=now_china())
        )
        await self.db.commit()

    async def list_devices(self, user_id: int) -> list[RunnerDevice]:
        return await self.repo.list_by_user(user_id)

    async def rename_device(self, user_id: int, device_id: int, name: str) -> RunnerDevice:
        device = await self._get_owned(user_id, device_id)
        device.name = name[:100]
        await self.db.commit()
        return device

    async def revoke_device(self, user_id: int, device_id: int) -> RunnerDevice:
        """吊销设备：状态置 revoked，WS 层据 hello 认证结果拒收。"""
        device = await self._get_owned(user_id, device_id)
        device.status = "revoked"
        await self.db.commit()
        logger.info("runner 设备已吊销", device_id=device_id, user_id=user_id)
        return device

    async def _get_owned(self, user_id: int, device_id: int) -> RunnerDevice:
        device = await self.repo.get_owned(user_id, device_id)
        if device is None:
            raise RunnerDeviceNotFoundError(device_id)
        return device
