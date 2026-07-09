"""
知识库仓储

处理知识库的数据访问操作
支持空间层级
"""

from typing import Optional, List, Dict, Any

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.knowledge_space.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseStatus,
)
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class KnowledgeBaseRepository:
    """
    知识库仓储

    处理知识库的 CRUD 操作
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = logger

    @staticmethod
    def _escape_ilike(keyword: str) -> str:
        """转义 ilike 查询中的通配符（% 和 _）"""
        return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    async def create(self, data: Dict[str, Any]) -> KnowledgeBase:
        """
        创建知识库

        Args:
            data: 知识库数据字典

        Returns:
            创建的知识库实例
        """
        kb = KnowledgeBase(**data)
        self.session.add(kb)
        await self.session.flush()
        await self.session.refresh(kb)
        return kb

    async def get_by_id(
        self,
        kb_id: int,
        include_documents: bool = False,
    ) -> Optional[KnowledgeBase]:
        """
        根据 ID 获取知识库

        Args:
            kb_id: 知识库 ID
            include_documents: 是否加载文档

        Returns:
            知识库实例或 None
        """
        query = select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.deleted_at.is_(None),
        )

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_space(
        self,
        space_id: int,
        status: Optional[KnowledgeBaseStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[KnowledgeBase]:
        """
        获取空间内的知识库列表

        Args:
            space_id: 空间 ID
            status: 状态过滤
            skip: 跳过数量
            limit: 返回数量

        Returns:
            知识库列表
        """
        query = select(KnowledgeBase).where(
            KnowledgeBase.space_id == space_id,
            KnowledgeBase.deleted_at.is_(None),
        )

        if status is not None:
            query = query.where(KnowledgeBase.status == status)

        query = query.order_by(KnowledgeBase.created_at.desc())
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_name(
        self,
        space_id: int,
        name: str,
    ) -> Optional[KnowledgeBase]:
        """
        根据名称获取知识库（同一空间内名称唯一，不含软删除）

        Args:
            space_id: 空间 ID
            name: 知识库名称

        Returns:
            知识库实例或 None
        """
        result = await self.session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.space_id == space_id,
                KnowledgeBase.name == name,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_deleted_by_name(
        self,
        space_id: int,
        name: str,
    ) -> List[KnowledgeBase]:
        """
        根据名称获取已软删除的知识库（用于释放唯一约束占位）

        Args:
            space_id: 空间 ID
            name: 知识库名称

        Returns:
            软删除的知识库列表
        """
        result = await self.session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.space_id == space_id,
                KnowledgeBase.name == name,
                KnowledgeBase.deleted_at.isnot(None),
            )
        )
        return list(result.scalars().all())

    async def update(
        self,
        kb_id: int,
        data: Dict[str, Any],
    ) -> Optional[KnowledgeBase]:
        """
        更新知识库

        Args:
            kb_id: 知识库 ID
            data: 更新数据字典

        Returns:
            更新后的知识库实例或 None
        """
        kb = await self.get_by_id(kb_id)
        if not kb:
            return None

        _protected_fields = {"id", "space_id", "creator_id", "created_at", "deleted_at"}
        for key, value in data.items():
            if key not in _protected_fields and hasattr(kb, key):
                setattr(kb, key, value)

        await self.session.flush()
        await self.session.refresh(kb)
        return kb

    async def update_config(
        self,
        kb_id: int,
        config: Dict[str, Any],
    ) -> Optional[KnowledgeBase]:
        """
        更新知识库配置

        Args:
            kb_id: 知识库 ID
            config: 配置字典（合并到现有配置）

        Returns:
            更新后的知识库实例或 None
        """
        kb = await self.get_by_id(kb_id)
        if not kb:
            return None

        current_config = kb.get_config()
        merged_config = {**current_config, **config}
        kb.config = merged_config

        await self.session.flush()
        await self.session.refresh(kb)
        return kb

    async def delete(self, kb_id: int) -> bool:
        """
        软删除知识库

        Args:
            kb_id: 知识库 ID

        Returns:
            是否成功
        """
        kb = await self.get_by_id(kb_id)
        if not kb:
            return False

        kb.soft_delete()
        await self.session.flush()
        return True

    async def hard_delete(self, kb_id: int) -> bool:
        """
        硬删除知识库（从数据库彻底删除）

        Args:
            kb_id: 知识库 ID

        Returns:
            是否成功
        """
        result = await self.session.execute(
            delete(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        )
        return result.rowcount > 0

    async def restore(self, kb_id: int) -> Optional[KnowledgeBase]:
        """
        恢复已删除的知识库

        Args:
            kb_id: 知识库 ID

        Returns:
            恢复后的知识库实例或 None
        """
        result = await self.session.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        )
        kb = result.scalar_one_or_none()

        if not kb or not kb.deleted_at:
            return None

        kb.restore()
        await self.session.flush()
        await self.session.refresh(kb)
        return kb

    async def count_by_space(
        self,
        space_id: int,
        status: Optional[KnowledgeBaseStatus] = None,
    ) -> int:
        """
        统计空间内的知识库数量

        Args:
            space_id: 空间 ID
            status: 状态过滤

        Returns:
            知识库数量
        """
        query = select(func.count(KnowledgeBase.id)).where(
            KnowledgeBase.space_id == space_id,
            KnowledgeBase.deleted_at.is_(None),
        )

        if status is not None:
            query = query.where(KnowledgeBase.status == status)

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def search_by_name(
        self,
        keyword: str,
        skip: int = 0,
        limit: int = 20,
    ) -> List[KnowledgeBase]:
        """
        按名称搜索知识库

        Args:
            keyword: 搜索关键词
            skip: 跳过数量
            limit: 返回数量

        Returns:
            知识库列表
        """
        escaped_keyword = self._escape_ilike(keyword)
        result = await self.session.execute(
            select(KnowledgeBase)
            .where(
                KnowledgeBase.name.ilike(f"%{escaped_keyword}%", escape="\\"),
                KnowledgeBase.deleted_at.is_(None),
            )
            .order_by(KnowledgeBase.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_creator(
        self,
        creator_id: int,
        status: Optional[KnowledgeBaseStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[KnowledgeBase]:
        """
        获取用户创建的知识库列表

        Args:
            creator_id: 创建者 ID
            status: 状态过滤
            skip: 跳过数量
            limit: 返回数量

        Returns:
            知识库列表
        """
        query = select(KnowledgeBase).where(
            KnowledgeBase.creator_id == creator_id,
            KnowledgeBase.deleted_at.is_(None),
        )

        if status is not None:
            query = query.where(KnowledgeBase.status == status)

        query = query.order_by(KnowledgeBase.created_at.desc())
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())
