"""
审计日志服务

处理知识空间的审计日志记录和查询
"""

from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request

from novamind.features.knowledge_space.repository.audit_repository import AuditRepository
from novamind.features.knowledge_space.repository.space_repository import SpaceRepository
from novamind.features.knowledge_space.models.space_audit_log import SpaceAuditLog, AuditAction
from novamind.features.knowledge_space.api.exceptions import SpaceNotFoundError
from novamind.core.middleware.structured_logging import get_logger
from novamind.core.database.database import get_db_session


class AuditService:
    """
    审计日志服务

    记录知识空间内的所有操作，用于审计和追踪
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.audit_repo = AuditRepository(session)
        self.space_repo = SpaceRepository(session)
        self.logger = get_logger(__name__)

    async def log_action(
        self,
        space_id: int,
        user_id: int,
        action: str,
        request: Optional[Request] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        changes: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        记录操作日志

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
            创建的审计日志
        """
        # 使用模型提供的 create_from_request 方法创建日志，并通过独立会话写入
        log = SpaceAuditLog.create_from_request(
            space_id=space_id,
            user_id=user_id,
            action=action,
            request=request,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=None,
            details=details,
            changes=changes,
        )

        # 设计说明：审计日志使用独立 session，不参与主事务回滚
        # 这是刻意设计：审计日志应始终记录，即使业务操作失败
        async with get_db_session() as audit_session:
            audit_session.add(log)
            await audit_session.commit()

        self.logger.info(
            "审计日志记录",
            space_id=space_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
        )

        return log

    async def log_space_create(
        self,
        space_id: int,
        user_id: int,
        space_name: str,
        request: Optional[Request] = None,
    ):
        """记录空间创建"""
        await self.log_action(
            space_id=space_id,
            user_id=user_id,
            action=AuditAction.SPACE_CREATE.value,
            resource_type="space",
            resource_id=space_id,
            details={"space_name": space_name},
            request=request,
        )

    async def log_space_update(
        self,
        space_id: int,
        user_id: int,
        changes: Dict[str, Any],
        request: Optional[Request] = None,
    ):
        """记录空间更新"""
        await self.log_action(
            space_id=space_id,
            user_id=user_id,
            action=AuditAction.SPACE_UPDATE.value,
            resource_type="space",
            resource_id=space_id,
            changes=changes,
            request=request,
        )

    async def log_space_delete(
        self,
        space_id: int,
        user_id: int,
        request: Optional[Request] = None,
    ):
        """记录空间删除"""
        await self.log_action(
            space_id=space_id,
            user_id=user_id,
            action=AuditAction.SPACE_DELETE.value,
            resource_type="space",
            resource_id=space_id,
            request=request,
        )

    async def log_kb_create(
        self,
        space_id: int,
        user_id: int,
        kb_id: int,
        kb_name: str,
        request: Optional[Request] = None,
    ):
        """记录知识库创建"""
        await self.log_action(
            space_id=space_id,
            user_id=user_id,
            action=AuditAction.KB_CREATE.value,
            resource_type="knowledge_base",
            resource_id=kb_id,
            details={"kb_name": kb_name},
            request=request,
        )

    async def log_kb_update(
        self,
        space_id: int,
        user_id: int,
        kb_id: int,
        changes: Dict[str, Any],
        request: Optional[Request] = None,
    ):
        """记录知识库更新"""
        await self.log_action(
            space_id=space_id,
            user_id=user_id,
            action=AuditAction.KB_UPDATE.value,
            resource_type="knowledge_base",
            resource_id=kb_id,
            changes=changes,
            request=request,
        )

    async def log_kb_delete(
        self,
        space_id: int,
        user_id: int,
        kb_id: int,
        kb_name: str,
        request: Optional[Request] = None,
    ):
        """记录知识库删除"""
        await self.log_action(
            space_id=space_id,
            user_id=user_id,
            action=AuditAction.KB_DELETE.value,
            resource_type="knowledge_base",
            resource_id=kb_id,
            details={"kb_name": kb_name},
            request=request,
        )

    async def log_member_invite(
        self,
        space_id: int,
        user_id: int,
        invited_user_id: int,
        role: str,
        request: Optional[Request] = None,
    ):
        """记录成员邀请"""
        await self.log_action(
            space_id=space_id,
            user_id=user_id,
            action=AuditAction.MEMBER_INVITE.value,
            resource_type="member",
            resource_id=invited_user_id,
            details={"invited_user_id": invited_user_id, "role": role},
            request=request,
        )

    async def log_document_upload(
        self,
        space_id: int,
        user_id: int,
        document_id: int,
        filename: str,
        file_size: int,
        request: Optional[Request] = None,
    ):
        """记录文档上传"""
        await self.log_action(
            space_id=space_id,
            user_id=user_id,
            action=AuditAction.DOCUMENT_UPLOAD.value,
            resource_type="document",
            resource_id=document_id,
            details={"filename": filename, "file_size": file_size},
            request=request,
        )

    async def log_document_delete(
        self,
        space_id: int,
        user_id: int,
        document_id: int,
        filename: str,
        request: Optional[Request] = None,
    ):
        """记录文档删除"""
        await self.log_action(
            space_id=space_id,
            user_id=user_id,
            action=AuditAction.DOCUMENT_DELETE.value,
            resource_type="document",
            resource_id=document_id,
            details={"filename": filename},
            request=request,
        )

    async def log_search(
        self,
        space_id: int,
        user_id: int,
        query: str,
        search_type: str,
        result_count: int,
        request: Optional[Request] = None,
    ):
        """记录检索操作"""
        action_map = {
            "vector": AuditAction.SEARCH_VECTOR.value,
            "bm25": AuditAction.SEARCH_BM25.value,
            "hybrid": AuditAction.SEARCH_HYBRID.value,
        }

        await self.log_action(
            space_id=space_id,
            user_id=user_id,
            action=action_map.get(search_type, AuditAction.SEARCH_HYBRID.value),
            resource_type="search",
            details={
                "query": query[:200],  # 截断查询
                "search_type": search_type,
                "result_count": result_count,
            },
            request=request,
        )

    async def get_space_logs(
        self,
        space_id: int,
        user_id: int,
        action: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 100,
        raise_not_found: bool = False,
    ) -> List[Any]:
        """
        获取空间审计日志

        Args:
            space_id: 空间 ID
            user_id: 用户 ID
            action: 操作类型过滤
            start_time: 开始时间
            end_time: 结束时间
            skip: 茳过数量
            limit: 返回数量
            raise_not_found: 空间不存在时是否抛出异常

        Returns:
            审计日志列表
        Raises:
            SpaceNotFoundError: 空间不存在（当 raise_not_found=True 时)
        """
        # 检查空间是否存在
        if raise_not_found:
            space = await self.space_repo.get_by_id(space_id)
            if not space:
                raise SpaceNotFoundError(space_id)

        return await self.audit_repo.get_by_space(
            space_id=space_id,
            action=action,
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            skip=skip,
            limit=limit,
        )

    async def get_trace_logs(
        self,
        trace_id: str,
    ) -> List[Any]:
        """
        根据追踪 ID 获取日志链路

        Args:
            trace_id: 追踪 ID

        Returns:
            审计日志列表
        """
        return await self.audit_repo.get_by_trace_id(trace_id)

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
            操作统计字典
        """
        return await self.audit_repo.get_action_stats(
            space_id=space_id,
            start_time=start_time,
            end_time=end_time,
        )

    async def cleanup_old_logs(
        self,
        days: int = 90,
    ) -> int:
        """
        清理旧日志

        Args:
            days: 保留天数

        Returns:
            删除的数量
        """
        count = await self.audit_repo.delete_old_logs(days=days)
        await self.session.commit()

        self.logger.info(
            "审计日志清理完成",
            deleted_count=count,
            retention_days=days,
        )

        return count
