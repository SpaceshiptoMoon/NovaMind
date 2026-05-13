"""
知识空间仓储

处理知识空间的数据访问操作
支持 Redis 缓存
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from src.shared.utils.time_utils import now_china


def _deserialize_datetime_fields(data: dict, fields: list[str]) -> dict:
    """将缓存中的 ISO 字符串转回 datetime 对象"""
    for field in fields:
        if field in data and isinstance(data[field], str):
            try:
                data[field] = datetime.fromisoformat(data[field])
            except (ValueError, TypeError):
                pass
    return data

from sqlalchemy import select, update, delete, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.knowledge_space.models.knowledge_space import (
    KnowledgeSpace,
    SpaceStatus,
    SpaceVisibility,
)
from src.features.knowledge_space.models.space_member import SpaceMember, MemberStatus
from src.shared.cache.redis_client import get_redis_client
from src.core.middleware.structured_logging import get_logger


# 缓存 TTL 常量
SPACE_CACHE_TTL = 7200  # 2 小时
SPACE_STATS_CACHE_TTL = 600  # 10 分钟


class SpaceRepository:
    """
    知识空间仓储

    处理知识空间的 CRUD 操作，支持缓存
    """

    @staticmethod
    def _escape_ilike(keyword: str) -> str:
        """转义 ilike 查询中的通配符（% 和 _）"""
        return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def __init__(self, session: AsyncSession):
        self.session = session
        self._cache = None
        self.logger = get_logger(__name__)

    async def _get_cache(self):
        """获取 Redis 缓存客户端"""
        if self._cache is None:
            self._cache = await get_redis_client()
        return self._cache

    def _get_space_cache_key(self, space_id: int) -> str:
        """生成空间缓存键"""
        return f"space:{space_id}"

    def _get_space_stats_cache_key(self, space_id: int) -> str:
        """生成空间统计缓存键"""
        return f"space:stats:{space_id}"

    async def _cache_space(self, space: KnowledgeSpace) -> None:
        """缓存空间信息"""
        try:
            cache = await self._get_cache()
            cache_key = self._get_space_cache_key(space.id)
            await cache.set(cache_key, space.to_dict(), expire=SPACE_CACHE_TTL)
        except Exception as e:
            self.logger.warning("缓存空间信息失败", space_id=space.id, error=str(e))

    async def _invalidate_space_cache(self, space_id: int) -> None:
        """失效空间相关缓存"""
        try:
            cache = await self._get_cache()
            # 删除空间基本信息缓存
            await cache.delete(self._get_space_cache_key(space_id))
            # 删除空间统计缓存
            await cache.delete(self._get_space_stats_cache_key(space_id))
            self.logger.debug("空间缓存已失效", space_id=space_id)
        except Exception as e:
            self.logger.warning("失效空间缓存失败", space_id=space_id, error=str(e))

    async def create(self, data: Dict[str, Any]) -> KnowledgeSpace:
        """
        创建知识空间

        Args:
            data: 空间数据字典

        Returns:
            创建的知识空间实例
        """
        space = KnowledgeSpace(**data)
        self.session.add(space)
        await self.session.flush()
        await self.session.refresh(space)
        return space

    async def get_by_id(
        self,
        space_id: int,
        use_cache: bool = True,
    ) -> Optional[KnowledgeSpace]:
        """
        根据 ID 获取知识空间（带缓存）

        Args:
            space_id: 空间 ID
            use_cache: 是否使用缓存

        Returns:
            知识空间实例或 None
        """
        # 尝试从缓存获取
        if use_cache:
            try:
                cache = await self._get_cache()
                cache_key = self._get_space_cache_key(space_id)
                cached_data = await cache.get(cache_key)

                if cached_data is not None:
                    self.logger.debug("空间缓存命中", space_id=space_id)
                    # 先尝试从 session identity map 获取
                    space = await self.session.get(KnowledgeSpace, space_id)
                    if space is not None:
                        return space
                    # 缓存命中但 session 中无数据，merge 到 session 以支持后续修改持久化
                    space = KnowledgeSpace(**cached_data)
                    space = await self.session.merge(space)
                    return space
            except Exception as e:
                self.logger.warning("读取空间缓存失败", space_id=space_id, error=str(e))

        # 从数据库获取（排除已软删除的空间）
        query = select(KnowledgeSpace).where(
            KnowledgeSpace.id == space_id,
            KnowledgeSpace.deleted_at.is_(None),
        )

        result = await self.session.execute(query)
        space = result.scalar_one_or_none()

        # 缓存结果
        if space and use_cache:
            await self._cache_space(space)

        return space

    async def get_by_name_and_owner(
        self,
        name: str,
        owner_id: int,
    ) -> Optional[KnowledgeSpace]:
        """
        根据名称和所有者获取知识空间

        Args:
            name: 空间名称
            owner_id: 所有者 ID

        Returns:
            知识空间实例或 None
        """
        result = await self.session.execute(
            select(KnowledgeSpace).where(
                KnowledgeSpace.name == name,
                KnowledgeSpace.owner_id == owner_id,
                KnowledgeSpace.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name(
        self,
        name: str,
    ) -> Optional[KnowledgeSpace]:
        """
        根据名称获取知识空间

        Args:
            name: 空间名称

        Returns:
            知识空间实例或 None
        """
        result = await self.session.execute(
            select(KnowledgeSpace).where(
                KnowledgeSpace.name == name,
                KnowledgeSpace.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_owner(
        self,
        owner_id: int,
        include_deleted: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> List[KnowledgeSpace]:
        """
        获取用户创建的空间列表

        Args:
            owner_id: 所有者 ID
            include_deleted: 是否包含已删除的
            skip: 跳过数量
            limit: 返回数量

        Returns:
            知识空间列表
        """
        query = select(KnowledgeSpace).where(
            KnowledgeSpace.owner_id == owner_id
        )

        if not include_deleted:
            query = query.where(KnowledgeSpace.status != SpaceStatus.DELETED)
            query = query.where(KnowledgeSpace.deleted_at.is_(None))

        query = query.order_by(KnowledgeSpace.created_at.desc())
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_user_spaces(
        self,
        user_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> List[KnowledgeSpace]:
        """
        获取用户的空间列表（通过成员关系）

        Args:
            user_id: 用户 ID
            skip: 跳过数量
            limit: 返回数量

        Returns:
            知识空间列表
        """
        query = (
            select(KnowledgeSpace)
            .join(
                SpaceMember,
                SpaceMember.space_id == KnowledgeSpace.id,
            )
            .where(
                SpaceMember.user_id == user_id,
                SpaceMember.status == MemberStatus.ACTIVE,
                KnowledgeSpace.status != SpaceStatus.DELETED,
                KnowledgeSpace.deleted_at.is_(None),
            )
            .order_by(SpaceMember.joined_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_user_spaces(self, user_id: int) -> int:
        """
        统计用户所属的空间数量

        Args:
            user_id: 用户 ID

        Returns:
            空间数量
        """
        query = (
            select(func.count(KnowledgeSpace.id))
            .join(
                SpaceMember,
                SpaceMember.space_id == KnowledgeSpace.id,
            )
            .where(
                SpaceMember.user_id == user_id,
                SpaceMember.status == MemberStatus.ACTIVE,
                KnowledgeSpace.status != SpaceStatus.DELETED,
                KnowledgeSpace.deleted_at.is_(None),
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_public_spaces(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> List[KnowledgeSpace]:
        """
        获取公开空间列表

        Args:
            skip: 跳过数量
            limit: 返回数量

        Returns:
            公开知识空间列表
        """
        query = select(KnowledgeSpace).where(
            KnowledgeSpace.visibility == SpaceVisibility.PUBLIC,
            KnowledgeSpace.status == SpaceStatus.ACTIVE,
            KnowledgeSpace.deleted_at.is_(None),
        ).order_by(KnowledgeSpace.created_at.desc())

        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_public_spaces(self) -> int:
        """
        统计公开空间数量

        Returns:
            公开空间数量
        """
        query = select(func.count(KnowledgeSpace.id)).where(
            KnowledgeSpace.visibility == SpaceVisibility.PUBLIC,
            KnowledgeSpace.status == SpaceStatus.ACTIVE,
            KnowledgeSpace.deleted_at.is_(None),
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def search(
        self,
        keyword: str,
        user_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[KnowledgeSpace]:
        """
        搜索知识空间

        Args:
            keyword: 搜索关键词
            user_id: 用户 ID（限制为用户可访问的空间）
            skip: 跳过数量
            limit: 返回数量

        Returns:
            匹配的知识空间列表
        """
        # 转义通配符，防止用户输入的 % 和 _ 被当作通配符
        escaped_keyword = self._escape_ilike(keyword)
        query = select(KnowledgeSpace).where(
            KnowledgeSpace.status == SpaceStatus.ACTIVE,
            KnowledgeSpace.deleted_at.is_(None),
            KnowledgeSpace.name.ilike(f"%{escaped_keyword}%", escape="\\"),
        )

        # 如果指定了用户，只返回用户可访问的空间
        if user_id:
            query = query.join(
                SpaceMember,
                SpaceMember.space_id == KnowledgeSpace.id,
            ).where(
                SpaceMember.user_id == user_id,
                SpaceMember.status == MemberStatus.ACTIVE,
            )

        query = query.order_by(KnowledgeSpace.created_at.desc())
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_search(
        self,
        keyword: str,
        user_id: Optional[int] = None,
    ) -> int:
        """
        统计搜索结果数量

        Args:
            keyword: 搜索关键词
            user_id: 用户 ID（限制为用户可访问的空间）

        Returns:
            匹配的空间数量
        """
        escaped_keyword = self._escape_ilike(keyword)
        query = select(func.count(KnowledgeSpace.id)).where(
            KnowledgeSpace.status == SpaceStatus.ACTIVE,
            KnowledgeSpace.deleted_at.is_(None),
            KnowledgeSpace.name.ilike(f"%{escaped_keyword}%", escape="\\"),
        )

        if user_id:
            query = query.join(
                SpaceMember,
                SpaceMember.space_id == KnowledgeSpace.id,
            ).where(
                SpaceMember.user_id == user_id,
                SpaceMember.status == MemberStatus.ACTIVE,
            )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def update(
        self,
        space_id: int,
        data: Dict[str, Any],
    ) -> Optional[KnowledgeSpace]:
        """
        更新知识空间（同时失效缓存）

        Args:
            space_id: 空间 ID
            data: 更新数据

        Returns:
            更新后的知识空间实例或 None
        """
        space = await self.get_by_id(space_id, use_cache=False)
        if not space:
            return None

        _protected_fields = {"id", "created_at", "deleted_at"}
        for key, value in data.items():
            if key not in _protected_fields and hasattr(space, key):
                setattr(space, key, value)

        await self.session.flush()
        await self.session.refresh(space)

        # 失效缓存
        await self._invalidate_space_cache(space_id)

        return space

    async def soft_delete(self, space_id: int) -> bool:
        """
        软删除知识空间（同时失效缓存）

        Args:
            space_id: 空间 ID

        Returns:
            是否成功
        """
        result = await self.session.execute(
            update(KnowledgeSpace)
            .where(KnowledgeSpace.id == space_id)
            .values(
                status=SpaceStatus.DELETED,
                deleted_at=now_china(),
            )
        )

        # 失效缓存
        if result.rowcount > 0:
            await self._invalidate_space_cache(space_id)

        return result.rowcount > 0

    async def hard_delete(self, space_id: int) -> bool:
        """
        硬删除知识空间

        Args:
            space_id: 空间 ID

        Returns:
            是否成功
        """
        result = await self.session.execute(
            delete(KnowledgeSpace).where(KnowledgeSpace.id == space_id)
        )
        return result.rowcount > 0

    async def update_stats(
        self,
        space_id: int,
        storage_delta_mb: int = 0,
    ) -> bool:
        """
        更新空间统计信息（原子操作，避免并发问题）

        Args:
            space_id: 空间 ID
            storage_delta_mb: 存储空间变化（MB）

        Returns:
            是否成功
        """
        result = await self.session.execute(
            update(KnowledgeSpace)
            .where(KnowledgeSpace.id == space_id)
            .values(
                storage_used_mb=func.greatest(0, KnowledgeSpace.storage_used_mb + storage_delta_mb),
            )
        )

        if result.rowcount > 0:
            await self._invalidate_space_cache(space_id)
            return True

        return False

    async def get_user_spaces_joined(
        self,
        user_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> List[KnowledgeSpace]:
        """
        获取用户所属的空间列表（使用 JOIN 避免 N+1 查询）

        Args:
            user_id: 用户 ID
            skip: 跳过数量
            limit: 返回数量

        Returns:
            知识空间列表
        """
        query = (
            select(KnowledgeSpace)
            .join(
                SpaceMember,
                SpaceMember.space_id == KnowledgeSpace.id,
            )
            .where(
                SpaceMember.user_id == user_id,
                SpaceMember.status == MemberStatus.ACTIVE,
                KnowledgeSpace.status != SpaceStatus.DELETED,
                KnowledgeSpace.deleted_at.is_(None),
            )
        )

        query = query.order_by(SpaceMember.joined_at.desc())
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_by_creator(
        self,
        creator_id: int,
    ) -> int:
        """
        统计用户创建的空间数量

        Args:
            creator_id: 创建者 ID

        Returns:
            空间数量
        """
        query = select(func.count(KnowledgeSpace.id)).where(
            KnowledgeSpace.owner_id == creator_id,
            KnowledgeSpace.status != SpaceStatus.DELETED,
            KnowledgeSpace.deleted_at.is_(None),
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def invalidate_space_cache(self, space_id: int) -> None:
        """
        公开方法：失效空间相关缓存

        Args:
            space_id: 空间 ID
        """
        await self._invalidate_space_cache(space_id)

        # 清理该空间下所有知识库的搜索缓存
        try:
            cache = await self._get_cache()

            from src.features.knowledge_space.models.knowledge_base import KnowledgeBase
            stmt = select(KnowledgeBase.id).where(
                KnowledgeBase.space_id == space_id,
                KnowledgeBase.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            kb_ids = [row[0] for row in result.all()]

            total_deleted = 0
            for kb_id in kb_ids:
                deleted = await cache.delete_by_pattern(f"search:{kb_id}:*", batch_size=100)
                total_deleted += deleted

            if total_deleted > 0:
                self.logger.debug(
                    "空间检索缓存已清理",
                    space_id=space_id,
                    deleted_count=total_deleted,
                )
        except Exception as e:
            self.logger.warning("清理空间检索缓存失败", space_id=space_id, error=str(e))
