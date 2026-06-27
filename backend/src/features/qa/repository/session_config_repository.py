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
    "threshold": 70000,
    "target_tokens": 2000,
    "keep_recent": 6,
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

    async def _upsert(
        self,
        session_id: str,
        user_id: int,
        **columns: dict,
    ) -> SessionConfig:
        """
        通用 upsert：记录不存在则创建（compression 用默认），存在则只更新传入的列。

        三个配置列（compression_config / kb_bindings / llm_config）的更新共享此实现，
        各自只指定要写的列。注意：只 flush 不 commit，事务由上层（get_db）统一管理。
        """
        try:
            config = await self.get_by_session_id(session_id)
            if config is None:
                init = {"compression_config": DEFAULT_COMPRESSION_CONFIG}
                init.update(columns)
                config = SessionConfig(
                    session_id=session_id,
                    user_id=user_id,
                    **init,
                )
                self.session.add(config)
            else:
                config.user_id = user_id
                for col, val in columns.items():
                    setattr(config, col, val)
            await self.session.flush()
            await self.session.refresh(config)
            return config
        except Exception as e:
            self.logger.error("更新会话配置失败", session_id=session_id, error=str(e))
            raise

    async def upsert_rag_binding(
        self, session_id: str, user_id: int, rag_config: dict,
    ) -> SessionConfig:
        """绑定/更新会话知识库（会话级自动 RAG）"""
        return await self._upsert(session_id, user_id, kb_bindings=rag_config)

    async def update_compression(
        self, session_id: str, user_id: int, compression_config: dict,
    ) -> SessionConfig:
        """更新会话压缩配置（支持反复修改）"""
        return await self._upsert(session_id, user_id, compression_config=compression_config)

    async def update_llm_config(
        self, session_id: str, user_id: int, llm_config: dict,
    ) -> SessionConfig:
        """更新会话模型生成参数配置（支持反复修改）"""
        return await self._upsert(session_id, user_id, llm_config=llm_config)
