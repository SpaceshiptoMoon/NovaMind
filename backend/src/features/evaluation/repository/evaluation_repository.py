"""
测评模块仓储层

两个仓储类：
- EvaluationTestSetRepository: 测试集 CRUD
- EvaluationTaskRepository: 测评任务 CRUD
"""
from datetime import datetime, timedelta
from typing import Optional, List

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from novamind.features.evaluation.models.evaluation_task import (
    EvaluationTestSet,
    EvaluationTask,
    EvaluationStatus,
)
from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.utils.time_utils import now_china

logger = get_logger(__name__)


class EvaluationTestSetRepository:
    """测试集仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        space_id: int,
        kb_id: int,
        creator_id: int,
        name: str,
        filename: str,
        file_type: str,
        file_size: int,
        file_hash: str,
        storage: dict,
        total_cases: int,
    ) -> EvaluationTestSet:
        test_set = EvaluationTestSet(
            space_id=space_id,
            kb_id=kb_id,
            creator_id=creator_id,
            name=name,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            file_hash=file_hash,
            storage=storage,
            total_cases=total_cases,
        )
        self.session.add(test_set)
        await self.session.flush()
        await self.session.refresh(test_set)
        return test_set

    async def get_by_id(
        self,
        test_set_id: int,
        space_id: Optional[int] = None,
        kb_id: Optional[int] = None,
    ) -> Optional[EvaluationTestSet]:
        query = select(EvaluationTestSet).where(EvaluationTestSet.id == test_set_id)
        if space_id is not None:
            query = query.where(EvaluationTestSet.space_id == space_id)
        if kb_id is not None:
            query = query.where(EvaluationTestSet.kb_id == kb_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_id_and_kb(
        self, test_set_id: int, space_id: int, kb_id: int
    ) -> Optional[EvaluationTestSet]:
        result = await self.session.execute(
            select(EvaluationTestSet).where(
                EvaluationTestSet.id == test_set_id,
                EvaluationTestSet.space_id == space_id,
                EvaluationTestSet.kb_id == kb_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_kb(
        self,
        kb_id: int,
        space_id: int,
        skip: int = 0,
        limit: int = 20,
    ) -> List[EvaluationTestSet]:
        result = await self.session.execute(
            select(EvaluationTestSet)
            .where(
                EvaluationTestSet.kb_id == kb_id,
                EvaluationTestSet.space_id == space_id,
            )
            .order_by(EvaluationTestSet.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_kb(self, kb_id: int, space_id: int) -> int:
        result = await self.session.execute(
            select(func.count(EvaluationTestSet.id)).where(
                EvaluationTestSet.kb_id == kb_id,
                EvaluationTestSet.space_id == space_id,
            )
        )
        return result.scalar_one()

    async def has_active_tasks(self, test_set_id: int) -> bool:
        """检查是否有活跃任务（PENDING 或 RUNNING）"""
        result = await self.session.execute(
            select(func.count(EvaluationTask.id)).where(
                EvaluationTask.test_set_id == test_set_id,
                EvaluationTask.status.in_([
                    EvaluationStatus.PENDING,
                    EvaluationStatus.RUNNING,
                ]),
            )
        )
        return result.scalar_one() > 0

    async def delete(self, test_set_id: int) -> bool:
        test_set = await self.get_by_id(test_set_id)
        if test_set:
            await self.session.delete(test_set)
            await self.session.flush()
            return True
        return False


class EvaluationTaskRepository:
    """测评任务仓储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        test_set_id: int,
        user_id: int,
        name: str,
        config: Optional[dict] = None,
    ) -> EvaluationTask:
        task = EvaluationTask(
            test_set_id=test_set_id,
            user_id=user_id,
            name=name,
            config=config,
            status=EvaluationStatus.PENDING,
        )
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def get_by_id(self, task_id: int) -> Optional[EvaluationTask]:
        result = await self.session.execute(
            select(EvaluationTask)
            .options(selectinload(EvaluationTask.test_set))
            .where(EvaluationTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_kb(
        self, task_id: int, space_id: int, kb_id: int
    ) -> Optional[EvaluationTask]:
        result = await self.session.execute(
            select(EvaluationTask)
            .join(EvaluationTestSet)
            .options(selectinload(EvaluationTask.test_set))
            .where(
                EvaluationTask.id == task_id,
                EvaluationTestSet.space_id == space_id,
                EvaluationTestSet.kb_id == kb_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_kb(
        self,
        kb_id: int,
        space_id: int,
        skip: int = 0,
        limit: int = 20,
        status: Optional[int] = None,
    ) -> List[EvaluationTask]:
        query = (
            select(EvaluationTask)
            .join(EvaluationTestSet)
            .options(selectinload(EvaluationTask.test_set))
            .where(
                EvaluationTestSet.kb_id == kb_id,
                EvaluationTestSet.space_id == space_id,
            )
        )
        if status is not None:
            query = query.where(EvaluationTask.status == status)
        query = query.order_by(EvaluationTask.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_by_kb(
        self,
        kb_id: int,
        space_id: int,
        status: Optional[int] = None,
    ) -> int:
        query = (
            select(func.count(EvaluationTask.id))
            .join(EvaluationTestSet)
            .where(
                EvaluationTestSet.kb_id == kb_id,
                EvaluationTestSet.space_id == space_id,
            )
        )
        if status is not None:
            query = query.where(EvaluationTask.status == status)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def update_status(self, task_id: int, status: EvaluationStatus) -> None:
        task = await self.get_by_id(task_id)
        if task:
            task.status = status
            await self.session.flush()

    async def update_progress(self, task_id: int, progress: dict) -> None:
        task = await self.get_by_id(task_id)
        if task:
            task.progress = progress
            await self.session.flush()

    async def update_result_storage(self, task_id: int, result_storage: dict) -> None:
        task = await self.get_by_id(task_id)
        if task:
            task.result_storage = result_storage
            await self.session.flush()

    async def update_error(self, task_id: int, error_message: str) -> None:
        task = await self.get_by_id(task_id)
        if task:
            task.error_message = error_message
            task.status = EvaluationStatus.FAILED
            await self.session.flush()

    async def delete(self, task_id: int) -> bool:
        task = await self.get_by_id(task_id)
        if task:
            await self.session.delete(task)
            await self.session.flush()
            return True
        return False

    async def list_by_test_set(self, test_set_id: int) -> List[EvaluationTask]:
        """查询测试集下的所有任务"""
        result = await self.session.execute(
            select(EvaluationTask).where(EvaluationTask.test_set_id == test_set_id)
        )
        return list(result.scalars().all())

    async def get_orphan_tasks(
        self,
        pending_timeout_minutes: int = 10,
        running_timeout_minutes: int = 30,
    ) -> List[EvaluationTask]:
        """查询超时的 PENDING / RUNNING 任务（用于启动时恢复）"""
        pending_cutoff = now_china() - timedelta(minutes=pending_timeout_minutes)
        running_cutoff = now_china() - timedelta(minutes=running_timeout_minutes)
        result = await self.session.execute(
            select(EvaluationTask)
            .options(selectinload(EvaluationTask.test_set))
            .where(
                or_(
                    (EvaluationTask.status == EvaluationStatus.PENDING) & (EvaluationTask.created_at < pending_cutoff),
                    (EvaluationTask.status == EvaluationStatus.RUNNING) & (EvaluationTask.created_at < running_cutoff),
                )
            )
        )
        return list(result.scalars().all())
