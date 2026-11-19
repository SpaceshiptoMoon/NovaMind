"""知识库仓储：知识库的 CRUD 与空间层级查询（含 ilike 转义）。"""

from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseStatus,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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

    async def create(self, data: dict[str, Any]) -> KnowledgeBase:
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
    ) -> KnowledgeBase | None:
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
        status: KnowledgeBaseStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeBase]:
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

    async def get_active_kb_ids(self, space_id: int) -> list[int]:
        """查空间下全部未删除知识库的 ID（无分页上限）。

        供缓存失效等必须覆盖全量 KB 的场景——``get_by_space`` 默认
        limit=100，漏一个 KB 就漏一份旧检索缓存。

        Args:
            space_id: 空间 ID

        Returns:
            未删除知识库 ID 列表，按创建时间升序。
        """
        query = (
            select(KnowledgeBase.id)
            .where(
                KnowledgeBase.space_id == space_id,
                KnowledgeBase.deleted_at.is_(None),
            )
            .order_by(KnowledgeBase.created_at.asc())
        )
        result = await self.session.execute(query)
        return [row[0] for row in result.all()]

    async def get_active_by_space_ids(self, space_ids: list[int]) -> list[KnowledgeBase]:
        """批量获取多个空间的活跃知识库（全局检索 fan-out 目标解析用）。

        仅取 ACTIVE 且未软删的库——归档库本就不参与召回，前置过滤与服务层
        单库检索的归档拦截同语义。单查询避免逐空间 N+1。

        Args:
            space_ids: 空间 ID 列表（空列表直接返回空）。

        Returns:
            知识库列表（创建时间倒序）。
        """
        if not space_ids:
            return []

        query = (
            select(KnowledgeBase)
            .where(
                KnowledgeBase.space_id.in_(space_ids),
                KnowledgeBase.deleted_at.is_(None),
                KnowledgeBase.status == KnowledgeBaseStatus.ACTIVE,
            )
            .order_by(KnowledgeBase.created_at.desc())
        )

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_name(
        self,
        space_id: int,
        name: str,
    ) -> KnowledgeBase | None:
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
    ) -> list[KnowledgeBase]:
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
        data: dict[str, Any],
    ) -> KnowledgeBase | None:
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
        config: dict[str, Any],
    ) -> KnowledgeBase | None:
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

    async def restore(self, kb_id: int) -> KnowledgeBase | None:
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
        status: KnowledgeBaseStatus | None = None,
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
    ) -> list[KnowledgeBase]:
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
        status: KnowledgeBaseStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeBase]:
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
