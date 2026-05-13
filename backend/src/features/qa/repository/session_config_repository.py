"""
会话配置仓库

处理会话配置的 CRUD 操作
"""
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.qa.models.session_config import SessionConfig
from src.core.middleware.structured_logging import get_logger


# 默认压缩配置
DEFAULT_COMPRESSION_CONFIG = {
    "enable_compression": True,
    "strategy": "summary",
    "threshold": 3000,
    "target_tokens": 500,
    "keep_recent": 2,
    "custom_prompt": None,
}


class SessionConfigRepository:
    """会话配置仓库"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = get_logger(__name__)

    async def get_by_session_id(self, session_id: str) -> Optional[SessionConfig]:
        """
        根据会话 ID 获取配置

        Args:
            session_id: 会话 ID（UUID 格式）

        Returns:
            会话配置，如果不存在则返回 None
        """
        try:
            stmt = select(SessionConfig).where(
                SessionConfig.session_id == session_id,
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            self.logger.error("获取会话配置失败", session_id=session_id, error=str(e))
            raise

    async def create(
        self,
        session_id: str,
        user_id: int,
        compression_config: dict,
    ) -> SessionConfig:
        """
        创建会话配置

        注意：此方法只 flush 不 commit，事务由 Service 层统一管理

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            compression_config: 压缩配置

        Returns:
            创建的配置
        """
        try:
            config = SessionConfig(
                session_id=session_id,
                user_id=user_id,
                compression_config=compression_config,
            )
            self.session.add(config)
            await self.session.flush()
            await self.session.refresh(config)
            return config

        except Exception as e:
            self.logger.error("创建会话配置失败", session_id=session_id, error=str(e))
            raise

    async def delete(self, session_id: str) -> bool:
        """
        删除会话配置

        注意：此方法只 flush 不 commit，事务由 Service 层统一管理

        Args:
            session_id: 会话 ID

        Returns:
            是否删除成功
        """
        try:
            config = await self.get_by_session_id(session_id)
            if config:
                await self.session.delete(config)
                await self.session.flush()
                return True
            return False
        except Exception as e:
            self.logger.error("删除会话配置失败", session_id=session_id, error=str(e))
            raise
