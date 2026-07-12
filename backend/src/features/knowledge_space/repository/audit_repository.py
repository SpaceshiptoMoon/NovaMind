"""
审计日志仓储

处理空间审计日志的数据访问操作
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from novamind.shared.utils.time_utils import now_china

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.models.space_audit_log import SpaceAuditLog, AuditAction


class AuditRepository:
    """
    审计日志仓储

    处理审计日志的 CRUD 操作
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: Dict[str, Any]) -> SpaceAuditLog:
        """
        创建审计日志

        Args:
            data: 日志数据字典

        Returns:
            创建的审计日志实例
        """
        log = SpaceAuditLog(**data)
        self.session.add(log)
        await self.session.flush()
        await self.session.refresh(log)
        return log

    async def get_by_id(
        self,
        log_id: int,
    ) -> Optional[SpaceAuditLog]:
        """
        根据 ID 获取审计日志

        Args:
            log_id: 日志 ID

        Returns:
            审计日志实例或 None
        """
        query = select(SpaceAuditLog).where(SpaceAuditLog.id == log_id)

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_space(
        self,
        space_id: int,
        action: Optional[str] = None,
        user_id: Optional[int] = None,
        resource_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[SpaceAuditLog]:
        """
        获取空间的审计日志列表

        Args:
            space_id: 空间 ID
            action: 操作类型过滤
            user_id: 用户 ID 过滤
            resource_type: 资源类型过滤（从 resource JSON 字段中过滤）
            start_time: 开始时间
            end_time: 结束时间
            skip: 跳过数量
            limit: 返回数量

        Returns:
            审计日志列表
        """
        query = select(SpaceAuditLog).where(SpaceAuditLog.space_id == space_id)

        if action:
            query = query.where(SpaceAuditLog.action == action)
        if user_id:
            query = query.where(SpaceAuditLog.user_id == user_id)
        # 使用 MySQL JSON 函数在 SQL 层过滤 resource_type，避免应用层过滤
        if resource_type:
            query = query.where(
                func.json_extract(SpaceAuditLog.resource, "$.type").as_string() == resource_type
            )
        if start_time:
            query = query.where(SpaceAuditLog.created_at >= start_time)
        if end_time:
            query = query.where(SpaceAuditLog.created_at <= end_time)

        query = query.order_by(SpaceAuditLog.created_at.desc())
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_trace_id(
        self,
        trace_id: str,
    ) -> List[SpaceAuditLog]:
        """
        根据追踪 ID 获取审计日志（用于请求链路追踪）

        Args:
            trace_id: 追踪 ID

        Returns:
            审计日志列表
        """
        query = select(SpaceAuditLog).where(SpaceAuditLog.trace_id == trace_id)

        query = query.order_by(SpaceAuditLog.created_at.asc())

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_resource(
        self,
        resource_type: str,
        resource_id: int,
        space_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[SpaceAuditLog]:
        """
        获取资源的审计日志

        Args:
            resource_type: 资源类型（从 resource JSON 字段中过滤）
            resource_id: 资源 ID（从 resource JSON 字段中过滤）
            space_id: 空间 ID（SQL 层过滤，避免全表扫描）
            skip: 跳过数量
            limit: 返回数量

        Returns:
            审计日志列表
        """
        query = select(SpaceAuditLog)

        # 使用 space_id 在 SQL 层过滤，避免全表扫描
        if space_id is not None:
            query = query.where(SpaceAuditLog.space_id == space_id)

        # 使用 MySQL JSON 函数在 SQL 层过滤 resource_type 和 resource_id
        query = query.where(
            func.json_extract(SpaceAuditLog.resource, "$.type").as_string() == resource_type,
            func.json_extract(SpaceAuditLog.resource, "$.id").as_integer() == resource_id,
        )

        query = query.order_by(SpaceAuditLog.created_at.desc())
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_user(
        self,
        user_id: int,
        space_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[SpaceAuditLog]:
        """
        获取用户的操作日志

        Args:
            user_id: 用户 ID
            space_id: 空间 ID（可选）
            skip: 跳过数量
            limit: 返回数量

        Returns:
            审计日志列表
        """
        query = select(SpaceAuditLog).where(SpaceAuditLog.user_id == user_id)

        if space_id:
            query = query.where(SpaceAuditLog.space_id == space_id)

        query = query.order_by(SpaceAuditLog.created_at.desc())
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def delete_old_logs(
        self,
        days: int = 90,
        batch_size: int = 10000,
    ) -> int:
        """
        删除旧日志（数据清理）

        Args:
            days: 保留天数
            batch_size: 批量删除大小

        Returns:
            删除的数量
        """
        cutoff_date = now_china() - timedelta(days=days)

        result = await self.session.execute(
            delete(SpaceAuditLog).where(SpaceAuditLog.created_at < cutoff_date)
        )
        return result.rowcount

    async def delete_by_space(self, space_id: int) -> int:
        """
        删除空间的所有审计日志

        Args:
            space_id: 空间 ID

        Returns:
            删除的数量
        """
        result = await self.session.execute(
            delete(SpaceAuditLog).where(SpaceAuditLog.space_id == space_id)
        )
        return result.rowcount

    async def count_by_space(
        self,
        space_id: int,
        action: Optional[str] = None,
    ) -> int:
        """
        统计空间的审计日志数量

        Args:
            space_id: 空间 ID
            action: 操作类型过滤

        Returns:
            日志数量
        """
        query = select(func.count(SpaceAuditLog.id)).where(
            SpaceAuditLog.space_id == space_id
        )

        if action:
            query = query.where(SpaceAuditLog.action == action)

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_action_stats(
        self,
        space_id: int,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, int]:
        """
        获取空间操作统计

        Args:
            space_id: 空间 ID
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            操作统计字典 {action: count}
        """
        query = (
            select(
                SpaceAuditLog.action,
                func.count(SpaceAuditLog.id).label("count"),
            )
            .where(SpaceAuditLog.space_id == space_id)
            .group_by(SpaceAuditLog.action)
        )

        if start_time:
            query = query.where(SpaceAuditLog.created_at >= start_time)
        if end_time:
            query = query.where(SpaceAuditLog.created_at <= end_time)

        result = await self.session.execute(query)
        return {row.action: row.count for row in result.all()}

    async def create_from_request(
        self,
        space_id: int,
        user_id: int,
        action: str,
        request,
        resource_type: str = None,
        resource_id: int = None,
        details: dict = None,
        changes: dict = None,
    ) -> SpaceAuditLog:
        """
        从请求创建审计日志

        Args:
            space_id: 空间 ID
            user_id: 用户 ID
            action: 操作类型
            request: FastAPI Request 对象
            resource_type: 资源类型
            resource_id: 资源 ID
            details: 操作详情
            changes: 变更内容

        Returns:
            创建的审计日志实例
        """
        log = SpaceAuditLog.create_from_request(
            space_id=space_id,
            user_id=user_id,
            action=action,
            request=request,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            changes=changes,
        )
        self.session.add(log)
        await self.session.flush()
        await self.session.refresh(log)
        return log
