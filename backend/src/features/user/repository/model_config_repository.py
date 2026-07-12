"""
用户模型配置仓储

处理用户模型配置的数据访问操作
每条配置绑定具体用户
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from typing import Optional, List

from novamind.features.user.models.user_model_config import UserModelConfig, ModelType
from novamind.features.user.schemas.model_config_schema import (
    ModelConfigCreate,
    ModelConfigUpdate,
)
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


# 模型类型字符串到枚举的映射
MODEL_TYPE_MAP = {
    "llm": ModelType.LLM,
    "embedding": ModelType.EMBEDDING,
    "rerank": ModelType.RERANK,
    "vlm": ModelType.VLM,
    "multimodal_embedding": ModelType.MULTIMODAL_EMBEDDING,
    "asr": ModelType.ASR,
}

# 模型类型枚举到字符串的映射
MODEL_TYPE_STR = {
    ModelType.LLM: "llm",
    ModelType.EMBEDDING: "embedding",
    ModelType.RERANK: "rerank",
    ModelType.VLM: "vlm",
    ModelType.MULTIMODAL_EMBEDDING: "multimodal_embedding",
    ModelType.ASR: "asr",
}


class ModelConfigRepository:
    """用户模型配置仓储"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========== 基础查询 ==========

    async def get_by_id(self, config_id: int) -> Optional[UserModelConfig]:
        """根据配置 ID 获取"""
        stmt = select(UserModelConfig).where(UserModelConfig.id == config_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ========== 按模型名称查询 ==========

    async def get_by_user_and_model(
        self,
        user_id: int,
        model_type: str,
        model: str
    ) -> Optional[UserModelConfig]:
        """
        获取用户的指定模型配置

        Args:
            user_id: 用户 ID
            model_type: 模型类型 (llm/embedding/rerank)
            model: 模型名称（如 gpt-4o）

        Returns:
            用户配置，不存在返回 None
        """
        type_enum = MODEL_TYPE_MAP.get(model_type.lower())
        if not type_enum:
            return None

        stmt = select(UserModelConfig).where(
            UserModelConfig.user_id == user_id,
            UserModelConfig.model_type == type_enum.value,
            UserModelConfig.model == model,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_available_configs(
        self,
        user_id: int,
        model_type: str
    ) -> List[UserModelConfig]:
        """
        获取用户的可用配置

        Args:
            user_id: 用户 ID
            model_type: 模型类型

        Returns:
            配置列表
        """
        type_enum = MODEL_TYPE_MAP.get(model_type.lower())
        if not type_enum:
            return []

        stmt = select(UserModelConfig).where(
            UserModelConfig.user_id == user_id,
            UserModelConfig.model_type == type_enum.value,
        ).order_by(UserModelConfig.model)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_by_user(
        self,
        user_id: int,
        model_type: Optional[str] = None
    ) -> List[UserModelConfig]:
        """
        获取用户的模型配置列表

        Args:
            user_id: 用户 ID
            model_type: 可选，筛选模型类型

        Returns:
            配置列表
        """
        stmt = select(UserModelConfig).where(UserModelConfig.user_id == user_id)

        if model_type:
            type_enum = MODEL_TYPE_MAP.get(model_type.lower())
            if type_enum:
                stmt = stmt.where(UserModelConfig.model_type == type_enum.value)

        stmt = stmt.order_by(UserModelConfig.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_user(self, user_id: int, model_type: Optional[str] = None) -> int:
        """统计用户配置数量"""
        stmt = select(func.count(UserModelConfig.id)).where(UserModelConfig.user_id == user_id)

        if model_type:
            type_enum = MODEL_TYPE_MAP.get(model_type.lower())
            if type_enum:
                stmt = stmt.where(UserModelConfig.model_type == type_enum.value)

        result = await self.db.execute(stmt)
        return result.scalar() or 0

    # ========== 创建/更新/删除 ==========

    async def create(
        self,
        user_id: int,
        data: ModelConfigCreate
    ) -> UserModelConfig:
        """
        创建模型配置

        Args:
            user_id: 用户 ID
            data: 配置数据

        Returns:
            创建的配置对象
        """
        type_enum = MODEL_TYPE_MAP.get(data.model_type.lower(), ModelType.LLM)

        config = UserModelConfig(
            user_id=user_id,
            model_type=type_enum.value,
            protocol=data.protocol,
            model=data.model,
            base_url=data.base_url,
            api_key=data.api_key,
            extra_config=data.extra_config,
        )

        self.db.add(config)
        await self.db.flush()
        await self.db.refresh(config)
        return config

    async def update(
        self,
        config: UserModelConfig,
        data: ModelConfigUpdate
    ) -> UserModelConfig:
        """
        更新模型配置

        Args:
            config: 配置对象
            data: 更新数据

        Returns:
            更新后的配置对象
        """
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(config, field, value)

        await self.db.flush()
        await self.db.refresh(config)
        return config

    async def delete(self, config_id: int) -> bool:
        """
        删除配置

        Returns:
            删除成功返回 True，配置不存在返回 False
        """
        stmt = delete(UserModelConfig).where(UserModelConfig.id == config_id)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount > 0

    async def delete_by_user(self, user_id: int) -> int:
        """
        删除用户的所有配置

        Returns:
            删除的记录数
        """
        stmt = delete(UserModelConfig).where(UserModelConfig.user_id == user_id)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount
