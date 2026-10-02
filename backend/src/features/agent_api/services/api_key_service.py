"""API key 服务：生成/加密存储/吊销/鉴权。

鉴权流程（最简正确方案）：请求明文 → SHA-256 → key_hash 唯一索引等值查找 →
status=active 且关联用户可用 → 直接信任（256-bit 高熵随机串 hash 命中即持钥
证明，与密码摘要校验同构；不解密比对——无安全增益且耦合加密密钥可用性）。
用户状态校验复用 user feature 的 get_auth_status（R2 公共面），保证 key 与
JWT 的用户禁用/删除语义永远一致。
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent_api.exceptions import (
    ApiKeyLimitExceededError,
    ApiKeyNotFoundError,
    InvalidApiKeyError,
)
from novamind.features.agent_api.models.api_key import AgentApiKey, ApiKeyStatus
from novamind.features.agent_api.repository.api_key_repository import ApiKeyRepository
from novamind.shared.utils.crypto import encrypt_api_key_async
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# 每用户有效 key 上限（已吊销不占额）
MAX_ACTIVE_KEYS_PER_USER = 20


@dataclass
class ApiKeyAuthContext:
    """鉴权成功上下文（key 归属 + 与 get_current_user 兼容的用户 dict）"""

    user_id: int
    key_id: int
    key_name: str
    user: dict  # get_auth_status 形状：id/username/email/role_code/is_admin/status/...


def generate_api_key() -> tuple[str, str, str]:
    """生成 (明文, sha256 hexdigest, 展示前缀)。明文仅此一次返回给调用方。

    前缀 nvm_（下划线对齐 token_urlsafe 字符集 [A-Za-z0-9_-] 避免歧义）；
    token_urlsafe(32) ≈ 256-bit 熵。
    """
    raw = secrets.token_urlsafe(32)
    plain = f"nvm_{raw}"
    return plain, hashlib.sha256(plain.encode()).hexdigest(), plain[:12]


class ApiKeyService:
    """API key 生命周期服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ApiKeyRepository(session)

    async def create_key(self, user_id: int, name: str) -> tuple[AgentApiKey, str]:
        """创建 key，返回 (记录, 明文)。明文仅此一次返回。

        Raises:
            ApiKeyLimitExceededError: 有效 key 数达上限。
        """
        active_count = await self.repo.count_by_user(user_id)
        if active_count >= MAX_ACTIVE_KEYS_PER_USER:
            raise ApiKeyLimitExceededError(
                f"每用户最多 {MAX_ACTIVE_KEYS_PER_USER} 个有效 API key，请先吊销不用的 key"
            )

        plain, key_hash, key_prefix = generate_api_key()
        record = AgentApiKey(
            user_id=user_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            api_key=await encrypt_api_key_async(plain),
            status=ApiKeyStatus.ACTIVE.value,
        )
        record = await self.repo.create(record)
        logger.info("API key 已创建", user_id=user_id, key_id=record.id, key_prefix=key_prefix)
        return record, plain

    async def list_keys(self, user_id: int) -> list[AgentApiKey]:
        """用户的全部 key（含已吊销历史）。"""
        return await self.repo.list_by_user(user_id)

    async def revoke_key(self, user_id: int, key_id: int) -> AgentApiKey:
        """吊销 key（即时失效——鉴权路径无缓存）。

        Raises:
            ApiKeyNotFoundError: 不存在或不属于该用户（防横探）。
        """
        record = await self.repo.get_by_id_and_user(key_id, user_id)
        if record is None:
            raise ApiKeyNotFoundError()
        if record.is_active:
            record = await self.repo.revoke(record)
            logger.info("API key 已吊销", user_id=user_id, key_id=key_id)
        return record

    async def authenticate(self, plain_key: str) -> ApiKeyAuthContext:
        """X-API-Key 鉴权：hash 查找 → key 状态 → 关联用户状态。

        任何失败统一 InvalidApiKeyError(401)——不区分「不存在/已吊销/用户禁用」，
        防探测。成功后 fire-and-forget 更新 last_used_at（失败不影响鉴权）。

        Raises:
            InvalidApiKeyError: key 缺失/无效/已吊销/关联用户不可用。
        """
        if not plain_key:
            raise InvalidApiKeyError("缺少 API key")

        key_hash = hashlib.sha256(plain_key.encode()).hexdigest()
        record = await self.repo.get_by_hash(key_hash)
        if record is None or not record.is_active:
            raise InvalidApiKeyError()

        # 用户状态校验（与 JWT 链 get_current_user 同语义：禁用/删除的用户的
        # key 一并失效）。R2：user services 公共面，懒 import 防环。
        # get_auth_status 返回 dict（id/username/email/role_code/is_admin/
        # status/is_active/is_deleted/must_change_password）——同时作为
        # 兼容 user dict 的字段源，省二次查库。
        from novamind.features.user.services.user_service import UserService
        from novamind.features.user.repository.user_repository import UserRepository

        user_service = UserService(UserRepository(self.session))
        user = await user_service.get_auth_status(record.user_id)
        if user is None or not user.get("is_active"):
            raise InvalidApiKeyError()

        await self._touch_last_used_safe(record.id)
        return ApiKeyAuthContext(
            user_id=record.user_id, key_id=record.id, key_name=record.name,
            user=user,
        )

    async def _touch_last_used_safe(self, key_id: int) -> None:
        """last_used_at 更新（fire-and-forget：需要独立短会话——调用方会话
        可能随请求提交/关闭；失败仅告警）。"""
        try:
            from novamind.core.database.database import get_db_session

            async with get_db_session() as session:
                await ApiKeyRepository(session).touch_last_used(key_id)
                await session.commit()
        except Exception as e:
            logger.warning("last_used_at 更新失败（忽略）", key_id=key_id, error=str(e))
