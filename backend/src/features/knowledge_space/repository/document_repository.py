"""
文档仓储

处理文档的数据访问操作
支持知识库层级
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from src.shared.utils.time_utils import now_china

from sqlalchemy import select, update, delete, func, cast, Integer, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.features.knowledge_space.models.document import Document, DocumentStatus
from src.shared.cache.redis_client import get_redis_client
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


# 缓存 TTL 常量
DOCUMENT_HASH_CACHE_TTL = 1209600  # 14 天
DOCUMENT_CACHE_TTL = 7200  # 2 小时


class DocumentRepository:
    """
    文档仓储

    处理文档的 CRUD 操作，支持知识库层级
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

    async def create(self, data: Dict[str, Any]) -> Document:
        """
        创建文档

        Args:
            data: 文档数据字典

        Returns:
            创建的文档实例
        """
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
        status: Optional[DocumentStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Document]:
        """获取知识库内的文档列表"""
        return await self._list_by_parent(Document.kb_id, kb_id, status, skip, limit)

    async def get_by_space(
        self,
        space_id: int,
        status: Optional[DocumentStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Document]:
        """获取空间内的文档列表"""
        return await self._list_by_parent(Document.space_id, space_id, status, skip, limit)

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

    async def update_status(
        self,
        document_id: int,
        status: DocumentStatus,
        error_message: Optional[str] = None,
    ) -> Optional[Document]:
        """
        更新文档处理状态

        Args:
            document_id: 文档 ID
            status: 新状态
            error_message: 错误信息（可选）

        Returns:
            更新后的文档实例或 None
        """
        document = await self.get_by_id(document_id)
        if not document:
            return None

        document.status = status
        if error_message:
            document.set_error(error_message)

        await self.session.flush()
        await self.session.refresh(document)
        return document

    async def delete(self, document_id: int) -> bool:
        """
        软删除文档（设置 deleted_at 和 status，同时失效缓存）

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

        # 软删除：设置 deleted_at 和 status，修改 file_hash 以解除唯一约束
        # file_hash 是 varchar(64)，SHA-256 恰好 64 字符，不能直接 concat
        # 截断前缀 + 短后缀，确保总长度 ≤ 64: prefix(48) + "_del_"(5) + id(≤11) = 64
        deleted_hash = func.concat(
            func.substring(Document.file_hash, 1, 48),
            f"_del_{document_id}",
        )
        result = await self.session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(
                deleted_at=now_china(),
                status=DocumentStatus.DELETED,
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

        Args:
            kb_id: 知识库 ID

        Returns:
            软删除的文档数量
        """
        result = await self.session.execute(
            update(Document)
            .where(Document.kb_id == kb_id, Document.deleted_at.is_(None))
            .values(
                deleted_at=now_china(),
                status=DocumentStatus.DELETED,
            )
        )
        return result.rowcount

    async def count_by_kb(
        self,
        kb_id: int,
        status: Optional[DocumentStatus] = None,
    ) -> int:
        """
        统计知识库内的文档数量

        Args:
            kb_id: 知识库 ID
            status: 状态过滤

        Returns:
            文档数量
        """
        query = select(func.count(Document.id)).where(
            Document.kb_id == kb_id,
            Document.deleted_at.is_(None),
        )

        if status is not None:
            query = query.where(Document.status == status)

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_storage_size(self, kb_id: int) -> int:
        """
        获取知识库的存储使用量

        Args:
            kb_id: 知识库 ID

        Returns:
            存储大小（字节）
        """
        result = await self.session.execute(
            select(func.sum(Document.file_size)).where(
                Document.kb_id == kb_id,
                Document.status != DocumentStatus.FAILED,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalar() or 0

    async def get_kb_realtime_stats(self, kb_id: int) -> Dict[str, Any]:
        """实时统计知识库信息（排除软删除文档）"""
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
        """实时统计空间内文档信息（排除软删除文档）"""
        result = await self.session.execute(
            select(
                func.count(Document.id).label("document_count"),
                func.coalesce(func.sum(
                    cast(func.json_extract(Document.doc_metadata, "$.chunk_count"), Integer)
                ), 0).label("chunk_count"),
                func.coalesce(func.sum(Document.file_size), 0).label("total_size_bytes"),
            ).where(
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

    async def get_processing_documents(
        self,
        limit: int = 100,
    ) -> List[Document]:
        """获取正在处理中的文档（用于后台任务）"""
        return await self._get_by_status(DocumentStatus.PROCESSING, limit)

    async def get_uploaded_documents(
        self,
        limit: int = 100,
    ) -> List[Document]:
        """获取已上传的文档（用于拆分解析触发）"""
        return await self._get_by_status(DocumentStatus.UPLOADED, limit)

    # ---------- 共享私有方法 ----------

    async def _list_by_parent(
        self,
        column,
        parent_id: int,
        status: Optional[DocumentStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Document]:
        """按父级字段（kb_id 或 space_id）查询文档列表"""
        query = select(Document).where(
            column == parent_id,
            Document.deleted_at.is_(None),
        )
        if status is not None:
            query = query.where(Document.status == status)
        query = query.order_by(Document.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _get_by_status(
        self,
        status: DocumentStatus,
        limit: int = 100,
    ) -> List[Document]:
        """按状态查询文档列表"""
        query = select(Document).where(
            Document.status == status,
            Document.deleted_at.is_(None),
        ).order_by(Document.created_at.asc()).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def _build_stats_select(with_kb_id: bool = False):
        """构建统计查询的 select 子句"""
        columns = []
        if with_kb_id:
            columns.append(Document.kb_id)
        columns.extend([
            func.count(Document.id).label("document_count"),
            func.coalesce(func.sum(
                cast(func.json_extract(Document.doc_metadata, "$.chunk_count"), Integer)
            ), 0).label("chunk_count"),
            func.coalesce(func.sum(Document.file_size), 0).label("total_size_bytes"),
            func.coalesce(func.sum(case((Document.status == DocumentStatus.UPLOADED, 1), else_=0)), 0).label("uploaded"),
            func.coalesce(func.sum(case((Document.status == DocumentStatus.COMPLETED, 1), else_=0)), 0).label("completed"),
            func.coalesce(func.sum(case((Document.status == DocumentStatus.FAILED, 1), else_=0)), 0).label("failed"),
            func.coalesce(func.sum(case((Document.status == DocumentStatus.PROCESSING, 1), else_=0)), 0).label("processing"),
        ])
        return select(*columns)

    @staticmethod
    def _row_to_stats_dict(row) -> Dict[str, Any]:
        """将统计查询结果行转为字典"""
        return {
            "document_count": row.document_count,
            "chunk_count": row.chunk_count,
            "total_size_mb": round(row.total_size_bytes / (1024 * 1024), 2),
            "uploaded_documents": row.uploaded,
            "completed_documents": row.completed,
            "failed_documents": row.failed,
            "processing_documents": row.processing,
        }
