"""Agent API key 模型：外部 agent 访问凭证（kb-ops 战略第四环「任何 agent 都能接」的门禁）。

双存设计：key_hash（SHA-256，唯一索引等值校验——256-bit 高熵随机串 hash 命中即
持钥证明，不解密比对）+ api_key 密文（AES-256-GCM，对齐 R6 加密惯例，为未来
密钥轮换保留可逆通道）。key_prefix 为明文前 12 字符，展示与人工排查用。
"""
from enum import IntEnum

from novamind.core.database.base import BaseModel
from sqlalchemy import BigInteger, Column, DateTime, SmallInteger, String


class ApiKeyStatus(IntEnum):
    """key 状态：1=有效 2=已吊销"""

    ACTIVE = 1
    REVOKED = 2


class AgentApiKey(BaseModel):
    """外部 agent API key"""

    __tablename__ = "agent_api_keys"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True, comment="创建者用户ID（key 继承其权限链）")
    name = Column(String(100), nullable=False, comment="显示名（用户自起）")

    key_prefix = Column(String(16), nullable=False, index=True, comment="明文前 12 字符（nvm_+8 熵字符），展示用")
    key_hash = Column(String(64), nullable=False, unique=True, comment="SHA-256 hexdigest(明文)——等值校验键")
    api_key = Column(String(500), nullable=False, comment="明文的 AES-256-GCM 密文（可逆留存，校验路径不触碰）")

    status = Column(SmallInteger, nullable=False, default=ApiKeyStatus.ACTIVE.value, comment="1=active 2=revoked")
    revoked_at = Column(DateTime, nullable=True, comment="吊销时间")
    last_used_at = Column(DateTime, nullable=True, comment="最近一次成功鉴权时间")

    def __repr__(self) -> str:
        return f"<AgentApiKey(id={self.id}, user_id={self.user_id}, name='{self.name}', status={self.status})>"

    @property
    def is_active(self) -> bool:
        """key 是否有效（吊销即刻失效）。"""
        return self.status == ApiKeyStatus.ACTIVE.value
