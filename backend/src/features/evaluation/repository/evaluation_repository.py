"""测评模块仓储层：测试集与测评任务的数据库读写。"""
from datetime import timedelta

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.evaluation.models.evaluation_task import (
    EvaluationStatus,
    EvaluationTask,
    EvaluationTestSet,
)
from novamind.shared.utils.time_utils import now_china
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = get_logger(__name__)


class EvaluationTestSetRepository:
    """测试集仓储"""

    def __init__(self, session: AsyncSession):
        """绑定请求级异步会话，本仓储全部查询经该会话执行。"""
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
        """持久化新测试集并回填自增 ID（flush 不提交，提交由调用方控制）。

        Args:
            space_id: 所属空间 ID。
            kb_id: 所属知识库 ID。
            creator_id: 创建者用户 ID。
            name: 测试集展示名。
            filename: 原始上传文件名。
            file_type: 文件扩展名小写（json 或 csv），决定后续解析方式。
            file_size: 文件字节数。
            file_hash: 文件 SHA-256 十六进制哈希，用于完整性核对。
            storage: MinIO 存储信息 dict，创建时传空 dict，上传成功后回填。
            total_cases: 解析出的测试用例总数。

        Returns:
            回填 id 后的测试集 ORM 对象（未 commit）。
        """
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
        space_id: int | None = None,
        kb_id: int | None = None,
    ) -> EvaluationTestSet | None:
        """按 ID 查测试集，可选叠加空间/知识库过滤做归属收窄。

        Args:
            test_set_id: 测试集记录 ID。
            space_id: 可选，传入时把结果收窄到该空间，不匹配视为不存在。
            kb_id: 可选，传入时把结果收窄到该知识库，不匹配视为不存在。

        Returns:
            命中的测试集 ORM 对象；不存在或归属不匹配返回 None。
        """
        query = select(EvaluationTestSet).where(EvaluationTestSet.id == test_set_id)
        if space_id is not None:
            query = query.where(EvaluationTestSet.space_id == space_id)
        if kb_id is not None:
            query = query.where(EvaluationTestSet.kb_id == kb_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_id_and_kb(
        self, test_set_id: int, space_id: int, kb_id: int
    ) -> EvaluationTestSet | None:
        """按 ID + 空间 + 知识库三元组查测试集，供路由层归属校验。

        Args:
            test_set_id: 测试集记录 ID。
            space_id: 期望归属的空间 ID。
            kb_id: 期望归属的知识库 ID。

        Returns:
            三元组全部匹配返回 ORM 对象，任一不匹配返回 None。
        """
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
    ) -> list[EvaluationTestSet]:
        """分页列出知识库下测试集，按创建时间倒序。

        Args:
            kb_id: 知识库 ID。
            space_id: 空间 ID，与 kb_id 联合收窄。
            skip: 分页跳过条数。
            limit: 单页条数上限。

        Returns:
            测试集 ORM 列表，创建时间新到旧排列。
        """
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
        """统计知识库下测试集总数，与分页列表配对使用。

        Args:
            kb_id: 知识库 ID。
            space_id: 空间 ID，与 kb_id 联合收窄。

        Returns:
            该知识库下测试集总数。
        """
        result = await self.session.execute(
            select(func.count(EvaluationTestSet.id)).where(
                EvaluationTestSet.kb_id == kb_id,
                EvaluationTestSet.space_id == space_id,
            )
        )
        return result.scalar_one()

    async def has_active_tasks(self, test_set_id: int) -> bool:
        """检查该测试集下是否存在 PENDING 或 RUNNING 的活跃任务。

        Args:
            test_set_id: 测试集记录 ID。

        Returns:
            存在活跃任务返回 True，用作删除测试集前的守卫。
        """
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
        """删除测试集记录，目标存在返回 True（提交由调用方控制）。

        Args:
            test_set_id: 待删除的测试集记录 ID。

        Returns:
            记录存在并已删除返回 True；不存在返回 False。
        """
        test_set = await self.get_by_id(test_set_id)
        if test_set:
            await self.session.delete(test_set)
            await self.session.flush()
            return True
        return False


class EvaluationTaskRepository:
    """测评任务仓储"""

    def __init__(self, session: AsyncSession):
        """绑定请求级异步会话，本仓储全部查询经该会话执行。"""
        self.session = session

    async def create(
        self,
        test_set_id: int,
        user_id: int,
        name: str,
        config: dict | None = None,
    ) -> EvaluationTask:
        """创建 PENDING 状态测评任务并回填自增 ID（flush 不提交）。

        Args:
            test_set_id: 关联的测试集 ID。
            user_id: 发起任务的用户 ID。
            name: 任务展示名。
            config: 可选测评参数 dict（模型名、开关项等）；None 表示全用默认。

        Returns:
            PENDING 状态的任务 ORM 对象（未 commit）。
        """
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

    async def get_by_id(self, task_id: int) -> EvaluationTask | None:
        """按 ID 查任务并预加载关联测试集，供报告与对比读取归属信息。

        Args:
            task_id: 测评任务记录 ID。

        Returns:
            任务 ORM 对象（test_set 已预加载）；不存在返回 None。
        """
        result = await self.session.execute(
            select(EvaluationTask)
            .options(selectinload(EvaluationTask.test_set))
            .where(EvaluationTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_kb(
        self, task_id: int, space_id: int, kb_id: int
    ) -> EvaluationTask | None:
        """join 测试集按 ID + 空间 + 知识库查任务，供路由层归属校验。

        Args:
            task_id: 测评任务记录 ID。
            space_id: 期望归属的空间 ID。
            kb_id: 期望归属的知识库 ID。

        Returns:
            全部匹配返回任务 ORM 对象（test_set 已预加载），否则返回 None。
        """
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
        status: int | None = None,
    ) -> list[EvaluationTask]:
        """分页列出知识库下任务，可按状态过滤，按创建时间倒序。

        Args:
            kb_id: 知识库 ID。
            space_id: 空间 ID，与 kb_id 联合收窄。
            skip: 分页跳过条数。
            limit: 单页条数上限。
            status: 可选，EvaluationStatus 整数状态过滤；None 表示不过滤。

        Returns:
            任务 ORM 列表（test_set 已预加载），创建时间新到旧排列。
        """
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
        status: int | None = None,
    ) -> int:
        """统计知识库下任务总数，可按状态过滤，与分页列表配对使用。

        Args:
            kb_id: 知识库 ID。
            space_id: 空间 ID，与 kb_id 联合收窄。
            status: 可选，EvaluationStatus 整数状态过滤；None 表示不过滤。

        Returns:
            满足条件的任务总数。
        """
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
        """更新任务状态，任务不存在时静默跳过（flush 不提交）。

        Args:
            task_id: 测评任务记录 ID。
            status: 目标状态，EvaluationStatus 枚举值。
        """
        task = await self.get_by_id(task_id)
        if task:
            task.status = status
            await self.session.flush()

    async def update_progress(self, task_id: int, progress: dict) -> None:
        """更新任务进度 current/total，任务不存在时静默跳过。

        Args:
            task_id: 测评任务记录 ID。
            progress: 进度 dict（current 为已完成数、total 为总数），整体覆盖。
        """
        task = await self.get_by_id(task_id)
        if task:
            task.progress = progress
            await self.session.flush()

    async def update_result_storage(self, task_id: int, result_storage: dict) -> None:
        """回写结果文件 MinIO 存储信息，任务不存在时静默跳过。

        Args:
            task_id: 测评任务记录 ID。
            result_storage: 结果文件存储 dict（bucket/object_name/etag），整体覆盖。
        """
        task = await self.get_by_id(task_id)
        if task:
            task.result_storage = result_storage
            await self.session.flush()

    async def update_error(self, task_id: int, error_message: str) -> None:
        """记录错误信息并把任务标记为 FAILED（提交由调用方控制）。

        Args:
            task_id: 测评任务记录 ID。
            error_message: 面向用户的错误描述。

        Returns:
            无；任务不存在时不做任何写入。
        """
        task = await self.get_by_id(task_id)
        if task:
            task.error_message = error_message
            task.status = EvaluationStatus.FAILED
            await self.session.flush()

    async def delete(self, task_id: int) -> bool:
        """删除任务记录，目标存在返回 True。

        Args:
            task_id: 待删除的测评任务记录 ID。

        Returns:
            记录存在并已删除返回 True；不存在返回 False。
        """
        task = await self.get_by_id(task_id)
        if task:
            await self.session.delete(task)
            await self.session.flush()
            return True
        return False

    async def list_by_test_set(self, test_set_id: int) -> list[EvaluationTask]:
        """查询测试集下的所有任务，不分页（删除前收集结果文件用）。

        Args:
            test_set_id: 测试集记录 ID。

        Returns:
            该测试集全部任务 ORM 列表，无排序保证。
        """
        result = await self.session.execute(
            select(EvaluationTask).where(EvaluationTask.test_set_id == test_set_id)
        )
        return list(result.scalars().all())

    async def get_orphan_tasks(
        self,
        pending_timeout_minutes: int = 10,
        running_timeout_minutes: int = 30,
    ) -> list[EvaluationTask]:
        """按创建时间查超时的 PENDING / RUNNING 任务，供启动时恢复。

        Args:
            pending_timeout_minutes: PENDING 任务超时阈值（分钟），超过视为孤儿。
            running_timeout_minutes: RUNNING 任务超时阈值（分钟），超过视为孤儿。

        Returns:
            超时任务 ORM 列表（test_set 已预加载），可能为空。
        """
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
