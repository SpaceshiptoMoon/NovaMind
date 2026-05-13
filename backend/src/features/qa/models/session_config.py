"""
会话配置模型

存储会话的压缩配置信息
"""

from typing import Optional
from sqlalchemy import Column, BigInteger, String, Text, JSON

from src.core.database.base import BaseModel


class SessionConfig(BaseModel):
    """
    会话配置模型

    只存储压缩配置，LLM 配置由前端在对话时传入
    """
    __tablename__ = "qa_session_configs"
    __table_args__ = (
        {"comment": "QA 会话配置表，存储会话的压缩配置信息"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(36), nullable=False, unique=True, index=True, comment="会话ID（UUID格式）")
    user_id = Column(BigInteger, nullable=False, index=True, comment="用户ID")

    # 压缩配置（JSON 格式）
    compression_config = Column(
        JSON,
        nullable=False,
        default=lambda: {
            "enable_compression": True,
            "strategy": "summary",
            "threshold": 3000,
            "target_tokens": 500,
            "keep_recent": 2,
            "custom_prompt": None,
        },
        comment="压缩配置"
    )

    def __repr__(self) -> str:
        return f"<SessionConfig(session_id={self.session_id})>"

    # ========== 压缩配置访问方法 ==========

    def get_compression_config(self) -> dict:
        """获取压缩配置"""
        return self.compression_config or {}

    @property
    def enable_compression(self) -> bool:
        return self.get_compression_config().get("enable_compression", True)

    @property
    def compression_strategy(self) -> str:
        return self.get_compression_config().get("strategy", "summary")

    @property
    def compression_threshold(self) -> int:
        return self.get_compression_config().get("threshold", 3000)

    @property
    def compression_target_tokens(self) -> int:
        return self.get_compression_config().get("target_tokens", 500)

    @property
    def keep_recent_messages(self) -> int:
        return self.get_compression_config().get("keep_recent", 2)

    @property
    def custom_summary_prompt(self) -> Optional[str]:
        return self.get_compression_config().get("custom_prompt")

    def set_compression_config(
        self,
        enable_compression: bool = True,
        strategy: str = "summary",
        threshold: int = 3000,
        target_tokens: int = 500,
        keep_recent: int = 2,
        custom_prompt: Optional[str] = None,
    ) -> None:
        """设置压缩配置"""
        self.compression_config = {
            "enable_compression": enable_compression,
            "strategy": strategy,
            "threshold": threshold,
            "target_tokens": target_tokens,
            "keep_recent": keep_recent,
            "custom_prompt": custom_prompt,
        }

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "compression_config": self.compression_config,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
