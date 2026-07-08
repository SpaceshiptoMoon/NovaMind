"""
文档仓储

处理文档的数据访问操作
支持知识库层级

注意：处理状态已迁移至 DocumentTask 模型。
本文档仓储仅负责 Document（文件元数据）的 CRUD。
状态统计通过 LEFT JOIN document_tasks 实现。
"""

from typing import Optional, List, Dict, Any
from sqlalchemy import select, update, delete, func, cast, Integer, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import outerjoin, selectinload

from src.features.knowledge_space.models.document import Document
from src.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
from src.shared.utils.time_utils import now_china
from src.shared.cache.redis_client import get_redis_client
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


# 缓存 TTL 常量
DOCUMENT_HASH_CACHE_TTL = 1209600  # 14 天
DOCUMENT_CACHE_TTL = 7200  # 2 小时


class DocumentRepository:
    """
    文档仓储

    处理文档的 CRUD 操作，支持知识库层级。
    处理状态统计通过 LEFT JOIN document_tasks 获取最新 Task 状态。
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self._cache = None
        self.logger = logger

    async def _get_cache(self):
        """获取 Redis 缓存客户端"""
        if self._cache is None:
            self._cache = await get_redis_client()
        return self._cache

    def _get_doc_hash_cache_key(self, kb_id: int, file_hash: str) -> str:
        """生成文档哈希缓存键"""
        return f"doc:hash:{kb_id}:{file_hash}"

    def _get_doc_cache_key(self, document_id: int) -> str:
        """生成文档缓存键"""
        return f"doc:id:{document_id}"

    async def cache_document_hash(
        self,
        kb_id: int,
        file_hash: str,
        exists: bool,
    ) -> None:
        """缓存文档哈希检查结果"""
        try:
            cache = await self._get_cache()
            cache_key = self._get_doc_hash_cache_key(kb_id, file_hash)
            await cache.set(cache_key, {"exists": exists}, expire=DOCUMENT_HASH_CACHE_TTL)
        except Exception as e:
            self.logger.warning(
                "缓存文档哈希失败",
                kb_id=kb_id,
                file_hash=file_hash[:16],
                error=str(e),
            )

    async def _invalidate_document_cache(self, document_id: int) -> None:
        """失效文档缓存"""
        try:
            cache = await self._get_cache()
            await cache.delete(self._get_doc_cache_key(document_id))
        except Exception as e:
            self.logger.warning("失效文档缓存失败", document_id=document_id, error=str(e))

    # ========== CRUD ==========

    async def create(self, data: Dict[str, Any]) -> Document:
        """
        创建文档

        Args:
            data: 文档数据字典

        Returns:
            创建的文档实例
        """
        if "storage" not in data or data["storage"] is None:
            data = {**data, "storage": {}}

        document = Document(**data)
        self.session.add(document)
        await self.session.flush()
        await self.session.refresh(document)
        return document

    async def get_by_id(
        self,
        document_id: int,
    ) -> Optional[Document]:
        """
        根据 ID 获取文档

        注意：分块数据存储在 Elasticsearch 中，不在 MySQL 中
        如需获取分块，请使用 DocumentService.get_document_chunks()

        Args:
            document_id: 文档 ID

        Returns:
            文档实例或 None
        """
        query = select(Document).where(
            Document.id == document_id,
            Document.deleted_at.is_(None),
        )

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_kb(
        self,
        kb_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Document]:
        """获取知识库内的文档列表"""
        return await self._list_by_parent(Document.kb_id, kb_id, skip, limit)

    async def get_by_space(
        self,
        space_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Document]:
        """获取空间内的文档列表"""
        return await self._list_by_parent(Document.space_id, space_id, skip, limit)

    async def get_by_hash(
        self,
        kb_id: int,
        file_hash: str,
        use_cache: bool = True,
    ) -> Optional[Document]:
        """
        根据文件哈希获取文档（用于去重，带缓存）

        Args:
            kb_id: 知识库 ID
            file_hash: 文件哈希值
            use_cache: 是否使用缓存

        Returns:
            文档实例或 None
        """
        # 1. 尝试从缓存获取
        if use_cache:
            try:
                cache = await self._get_cache()
                cache_key = self._get_doc_hash_cache_key(kb_id, file_hash)
                cached = await cache.get(cache_key)

                if cached is not None:
                    self.logger.debug("文档哈希缓存命中", kb_id=kb_id, file_hash=file_hash[:16])
                    if not cached.get("exists", False):
                        return None
                    result = await self.session.execute(
                        select(Document).where(
                            Document.kb_id == kb_id,
                            Document.file_hash == file_hash,
                            Document.deleted_at.is_(None),
                        )
                    )
                    return result.scalar_one_or_none()
            except Exception as e:
                self.logger.warning(
                    "读取文档哈希缓存失败",
                    kb_id=kb_id,
                    file_hash=file_hash[:16],
                    error=str(e),
                )

        # 2. 从数据库查询（排除已软删除的文档）
        result = await self.session.execute(
            select(Document).where(
                Document.kb_id == kb_id,
                Document.file_hash == file_hash,
                Document.deleted_at.is_(None),
            )
        )
        document = result.scalar_one_or_none()

        # 3. 缓存结果
        if use_cache:
            try:
                cache = await self._get_cache()
                cache_key = self._get_doc_hash_cache_key(kb_id, file_hash)
                await cache.set(
                    cache_key,
                    {"exists": document is not None},
                    expire=DOCUMENT_HASH_CACHE_TTL,
                )
            except Exception as e:
                self.logger.warning(
                    "缓存文档哈希失败",
                    kb_id=kb_id,
                    file_hash=file_hash[:16],
                    error=str(e),
                )

        return document

    async def get_deleted_by_hash(self, kb_id: int, file_hash: str) -> Optional[Document]:
        """根据文件哈希获取已软删除的文档（用于复活）"""
        result = await self.session.execute(
            select(Document).where(
                Document.kb_id == kb_id,
                Document.file_hash == file_hash,
                Document.deleted_at.isnot(None),
            ).order_by(Document.deleted_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def delete(self, document_id: int) -> bool:
        """
        软删除文档（设置 deleted_at，同时失效缓存）

        Args:
            document_id: 文档 ID

        Returns:
            是否成功
        """
        document = await self.get_by_id(document_id)
        if not document:
            return False

        # 失效哈希缓存
        try:
            cache = await self._get_cache()
            hash_cache_key = self._get_doc_hash_cache_key(document.kb_id, document.file_hash)
            await cache.delete(hash_cache_key)
        except Exception as e:
            self.logger.warning(
                "失效文档哈希缓存失败",
                document_id=document_id,
                error=str(e),
            )

        # 软删除：设置 deleted_at，修改 file_hash 以解除唯一约束
        deleted_hash = func.concat(
            func.substring(Document.file_hash, 1, 48),
            f"_del_{document_id}",
        )
        result = await self.session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(
                deleted_at=now_china(),
                file_hash=deleted_hash,
            )
        )
        success = result.rowcount > 0

        if success:
            await self._invalidate_document_cache(document_id)

        return success

    async def delete_by_kb(self, kb_id: int) -> int:
        """
        软删除知识库内的所有文档

        注意：不级联软删除 DocumentTask，查询时通过 document.deleted_at IS NOT NULL 排除。

        Args:
            kb_id: 知识库 ID

        Returns:
            软删除的文档数量
        """
        result = await self.session.execute(
            update(Document)
            .where(Document.kb_id == kb_id, Document.deleted_at.is_(None))
            .values(deleted_at=now_china())
        )
        return result.rowcount

    async def count_by_kb(self, kb_id: int) -> int:
        """
        统计知识库内的文档数量

        Args:
            kb_id: 知识库 ID

        Returns:
            文档数量
        """
        query = select(func.count(Document.id)).where(
            Document.kb_id == kb_id,
            Document.deleted_at.is_(None),
        )
        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_storage_size(self, kb_id: int) -> int:
        """
        获取知识库的存储使用量（所有未删除文档的文件大小之和）

        Args:
            kb_id: 知识库 ID

        Returns:
            存储大小（字节）
        """
        result = await self.session.execute(
            select(func.sum(Document.file_size)).where(
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalar() or 0

    # ========== 统计查询 ==========

    async def get_kb_realtime_stats(self, kb_id: int) -> Dict[str, Any]:
        """实时统计知识库信息（排除软删除文档），通过 LEFT JOIN document_tasks 获取状态"""
        stmt = self._build_stats_select().where(
            Document.kb_id == kb_id,
            Document.deleted_at.is_(None),
        )
        row = (await self.session.execute(stmt)).one()
        return self._row_to_stats_dict(row)

    async def batch_get_kb_stats(self, kb_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """批量统计多个知识库信息（单条 SQL，解决 N+1 问题）"""
        if not kb_ids:
            return {}
        stmt = self._build_stats_select(with_kb_id=True).where(
            Document.kb_id.in_(kb_ids),
            Document.deleted_at.is_(None),
        ).group_by(Document.kb_id)
        result = await self.session.execute(stmt)
        return {row.kb_id: self._row_to_stats_dict(row) for row in result.all()}

    async def get_space_realtime_stats(self, space_id: int) -> Dict[str, Any]:
        """实时统计空间内文档信息（排除软删除文档）

        注意：chunk_count 从 document_tasks 的最新 COMPLETED 任务的 pipeline_result 聚合。
        """
        # 子查询：每个文档最新 COMPLETED 任务的 pipeline_result
        latest_completed_subq = (
            select(
                DocumentTask.document_id,
                DocumentTask.pipeline_result,
                func.row_number().over(
                    partition_by=DocumentTask.document_id,
                    order_by=DocumentTask.id.desc(),
                ).label("rn"),
            )
            .where(DocumentTask.status == TaskStatus.COMPLETED)
            .subquery()
        )

        latest_completed = (
            select(
                latest_completed_subq.c.document_id,
                latest_completed_subq.c.pipeline_result,
            )
            .where(latest_completed_subq.c.rn == 1)
            .subquery("latest_completed")
        )

        result = await self.session.execute(
            select(
                func.count(Document.id).label("document_count"),
                func.coalesce(func.sum(
                    cast(func.json_extract(latest_completed.c.pipeline_result, "$.chunk_count"), Integer)
                ), 0).label("chunk_count"),
                func.coalesce(func.sum(Document.file_size), 0).label("total_size_bytes"),
            )
            .select_from(
                outerjoin(
                    Document,
                    latest_completed,
                    latest_completed.c.document_id == Document.id,
                )
            )
            .where(
                Document.space_id == space_id,
                Document.deleted_at.is_(None),
            )
        )
        row = result.one()
        return {
            "document_count": row.document_count,
            "chunk_count": row.chunk_count,
            "total_size_mb": round(row.total_size_bytes / (1024 * 1024), 2),
        }

    async def search_by_filename(
        self,
        kb_id: int,
        keyword: str,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Document]:
        """
        按文件名搜索文档

        Args:
            kb_id: 知识库 ID
            keyword: 搜索关键词
            skip: 跳过数量
            limit: 返回数量

        Returns:
            文档列表
        """
        # 转义通配符，防止用户输入的 % 和 _ 被当作通配符
        escaped_keyword = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        result = await self.session.execute(
            select(Document)
            .where(
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
                Document.filename.ilike(f"%{escaped_keyword}%", escape="\\"),
            )
            .order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    # ---------- 私有方法 ----------

    async def _list_by_parent(
        self,
        column,
        parent_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Document]:
        """按父级字段（kb_id 或 space_id）查询文档列表"""
        query = (
            select(Document)
            .where(
                column == parent_id,
                Document.deleted_at.is_(None),
            )
            .order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def _build_stats_select(with_kb_id: bool = False):
        """
        构建统计查询的 select 子句

        通过 LEFT JOIN document_tasks（窗口函数取每个文档的最新一条 Task）
        获取当前处理状态和 chunk_count。

        无 Task 的文档视为 pending（status=0, PENDING）。
        """
        # 子查询：按 document_id 分区，取每个文档的最新 Task 记录
        ranked = (
            select(
                DocumentTask.document_id,
                DocumentTask.status,
                DocumentTask.pipeline_result,
                func.row_number().over(
                    partition_by=DocumentTask.document_id,
                    order_by=DocumentTask.id.desc(),
                ).label("rn"),
            ).subquery()
        )

        latest = (
            select(
                ranked.c.document_id.label("doc_id"),
                ranked.c.status.label("task_status"),
                ranked.c.pipeline_result.label("pipeline_result"),
            )
            .where(ranked.c.rn == 1)
            .subquery("latest_task")
        )

        columns = []
        if with_kb_id:
            columns.append(Document.kb_id)

        columns.extend([
            func.count(Document.id).label("document_count"),
            func.coalesce(func.sum(
                cast(func.json_extract(latest.c.pipeline_result, "$.chunk_count"), Integer)
            ), 0).label("chunk_count"),
            func.coalesce(func.sum(Document.file_size), 0).label("total_size_bytes"),
            # pending: 无 Task 或 Task.status == PENDING
            func.coalesce(func.sum(case(
                (latest.c.doc_id.is_(None), 1),
                (latest.c.task_status == TaskStatus.PENDING, 1),
                else_=0,
            )), 0).label("pending"),
            func.coalesce(func.sum(case(
                (latest.c.task_status == TaskStatus.COMPLETED, 1), else_=0
            )), 0).label("completed"),
            func.coalesce(func.sum(case(
                (latest.c.task_status == TaskStatus.FAILED, 1), else_=0
            )), 0).label("failed"),
            func.coalesce(func.sum(case(
                (latest.c.task_status == TaskStatus.PROCESSING, 1), else_=0
            )), 0).label("processing"),
        ])

        return select(*columns).select_from(
            outerjoin(Document, latest, latest.c.doc_id == Document.id)
        )

    @staticmethod
    def _row_to_stats_dict(row) -> Dict[str, Any]:
        """将统计查询结果行转为字典"""
        return {
            "document_count": row.document_count,
            "chunk_count": row.chunk_count,
            "total_size_mb": round(row.total_size_bytes / (1024 * 1024), 2),
            "pending_documents": row.pending,
            "completed_documents": row.completed,
            "failed_documents": row.failed,
            "processing_documents": row.processing,
        }
