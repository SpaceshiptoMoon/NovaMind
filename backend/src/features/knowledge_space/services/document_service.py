"""
文档管理服务

处理文档的上传、处理、删除等操作
支持多租户和知识库层级
使用 MinIO 对象存储和 Elasticsearch 向量检索

注意: 分块数据仅存储在 Elasticsearch 中，不在 MySQL 中存储
"""

from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.repository.space_repository import SpaceRepository
from novamind.features.knowledge_space.services.permission_service import PermissionService
from novamind.features.knowledge_space.exceptions import (
    KnowledgeBaseNotFoundError,
    DocumentNotFoundError,
    DocumentAlreadyProcessingError,
    SpaceAccessDeniedError,
)
from novamind.shared.storage.minio_client import MinioClient
from novamind.shared.model_config_ports import ModelConfigPort
from novamind.shared.storage.elasticsearch_client import ElasticsearchClient
from novamind.core.middleware.structured_logging import get_logger


class DocumentService:
    """
    文档管理服务

    处理文档的完整生命周期：上传 → 处理 → 分块 → 向量化 → ES 索引
    支持多租户和知识库层级
    """

    # 文件类型常量收敛到 document_file_types（upload 校验 + pipeline 分流 + 路由白名单三方共用）
    from novamind.features.knowledge_space.services.document_file_types import (
        MAX_FILE_SIZE,
        SUPPORTED_FILE_TYPES,
        IMAGE_FILE_TYPES,
        VIDEO_FILE_TYPES,
        AUDIO_FILE_TYPES,
        MODALITY_TO_FILE_TYPES,
    )

    def __init__(
        self,
        session: AsyncSession,
        minio_client: MinioClient,
        es_client: ElasticsearchClient,
        model_config_service: Optional[ModelConfigPort] = None,
    ):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.kb_repo = KnowledgeBaseRepository(session)
        self.space_repo = SpaceRepository(session)
        self.minio_client = minio_client
        self.es_client = es_client
        self.model_config_service = model_config_service
        self.logger = get_logger(__name__)
        self.member_repo = MemberRepository(session)
        self.permission_service = PermissionService()

    async def count_kb_documents(
        self,
        kb_id: int,
        status: Optional[int] = None,
    ) -> int:
        """统计知识库中的文档数量"""
        return await self.doc_repo.count_by_kb(kb_id=kb_id, status=status)

    async def delete_document(
        self,
        kb_id: int,
        document_id: int,
        user_id: int,
    ) -> bool:
        """
        删除文档

        权限规则：
        - EDITOR 及以上角色可删除自己上传的文档
        - ADMIN 可删除任意文档

        Args:
            kb_id: 知识库 ID
            document_id: 文档 ID
            user_id: 操作用户 ID

        Returns:
            是否成功

        Raises:
            DocumentNotFoundError: 文档不存在
            SpaceAccessDeniedError: 无权删除文档
        """
        # 1. 权限检查：验证成员身份和角色
        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb:
            raise KnowledgeBaseNotFoundError(kb_id)

        member = await self.member_repo.get_by_space_and_user(kb.space_id, user_id)
        if not member or not member.is_active():
            raise SpaceAccessDeniedError(kb.space_id, user_id, "无权删除此知识库的文档")
        if not self.permission_service.can_delete_document(member):
            raise SpaceAccessDeniedError(kb.space_id, user_id, "需要编辑者或更高权限才能删除文档")

        # 2. 获取文档
        document = await self.doc_repo.get_by_id(document_id)
        if not document or document.kb_id != kb_id:
            raise DocumentNotFoundError(document_id)

        # 2.5 有活跃处理任务时拒绝删除
        from novamind.features.knowledge_space.repository.document_task_repository import (
            DocumentTaskRepository,
        )

        _task_repo = DocumentTaskRepository(self.session)
        active_task = await _task_repo.get_active_by_document_id(document_id)
        if active_task:
            raise DocumentAlreadyProcessingError(document_id)

        # 3. 细粒度权限检查：EDITOR 只能删除自己的文档，ADMIN 可删除任意文档
        if not self.permission_service.can_delete_any_document(member):
            if document.uploader_id != user_id:
                raise SpaceAccessDeniedError(
                    kb.space_id,
                    user_id,
                    "只能删除自己上传的文档，删除他人文档需要管理员权限",
                )

        # 4. 删除文档记录（先数据库操作，确保事务一致性）
        await self.doc_repo.delete(document_id)

        # 5. 更新知识库统计（使用行锁保证原子性）
        await self.session.commit()

        # 6. 失效该知识库的搜索缓存
        try:
            from novamind.shared.cache.redis_client import get_redis_client

            cache = await get_redis_client()
            await cache.delete_by_pattern(f"search:{kb_id}:*", batch_size=100)
        except Exception as cache_err:
            self.logger.warning("搜索缓存失效失败", kb_id=kb_id, error=str(cache_err))

        # 7. 清理外部存储（DB 事务提交后再执行，失败不影响数据一致性）
        try:
            await self.es_client.delete_document_chunks(
                space_id=document.space_id,
                document_id=document_id,
            )
        except Exception as e:
            self.logger.warning(
                "删除 ES 分块数据失败（数据已从 DB 删除）", document_id=document_id, error=str(e)
            )

        try:
            storage_info = document.get_storage_info()
            if storage_info.get("minio_bucket") and storage_info.get("minio_object_name"):
                await self.minio_client.delete_document(
                    bucket_name=storage_info["minio_bucket"],
                    object_name=storage_info["minio_object_name"],
                )
        except Exception as e:
            self.logger.warning(
                "删除 MinIO 文件失败（数据已从 DB 删除）", document_id=document_id, error=str(e)
            )

        self.logger.info(
            "文档删除成功",
            document_id=document_id,
            kb_id=kb_id,
            user_id=user_id,
        )

        return True

    async def get_document(
        self,
        document_id: int,
        raise_not_found: bool = False,
    ) -> Optional[Document]:
        """
        获取文档

        Args:
            document_id: 文档 ID
            raise_not_found: 是否在文档不存在时抛出异常

        Returns:
            文档或 None
        """
        document = await self.doc_repo.get_by_id(document_id)
        if not document and raise_not_found:
            raise DocumentNotFoundError(document_id)
        return document

    async def get_kb_documents(
        self,
        kb_id: int,
        skip: int = 0,
        limit: int = 100,
        status: Optional[int] = None,
    ) -> List[Document]:
        """
        获取知识库的文档列表

        Args:
            kb_id: 知识库 ID
            skip: 跳过数量
            limit: 返回数量

        Returns:
            文档列表
        """
        return await self.doc_repo.get_by_kb(
            kb_id=kb_id,
            skip=skip,
            limit=limit,
            status=status,
        )

    async def get_document_chunks(
        self,
        space_id: int,
        document_id: int,
        skip: int = 0,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        获取文档的分块列表（从 Elasticsearch 获取，分页）

        Args:
            space_id: 空间 ID
            document_id: 文档 ID
            skip: 跳过的记录数
            limit: 返回的最大记录数

        Returns:
            ``{"items": [...], "total": int}`` — items 为当前页分块，total 为分块总数
        """
        return await self.es_client.get_document_chunks(
            space_id=space_id,
            document_id=document_id,
            skip=skip,
            limit=limit,
        )

    async def download_document(
        self,
        document_id: int,
    ) -> bytes:
        """
        下载文档

        Args:
            document_id: 文档 ID

        Returns:
            文件内容

        Raises:
            DocumentNotFoundError: 文档不存在
        """
        document = await self.doc_repo.get_by_id(document_id)
        if not document:
            raise DocumentNotFoundError(document_id)

        storage_info = document.get_storage_info()
        return await self.minio_client.download_document(
            bucket_name=storage_info.get("minio_bucket"),
            object_name=storage_info.get("minio_object_name"),
        )

    async def get_parsed_text(self, document_id: int) -> Optional[bytes]:
        """获取文档解析后的 Markdown 全文。

        从 MinIO 读取 document.storage["parsed_text_object"] 指向的文件。
        若文档尚未解析或解析结果不存在，返回 None。

        Args:
            document_id: 文档 ID

        Returns:
            Markdown 全文的字节数据，或 None
        """
        from novamind.shared.storage.client_factory import ClientFactory

        document = await self.doc_repo.get_by_id(document_id)
        if not document:
            return None

        storage_info = document.get_storage_info()
        parsed_text_object = storage_info.get("parsed_text_object", "")
        if not parsed_text_object:
            return None

        try:
            minio_client = await ClientFactory.get_minio_client()
            content = await minio_client.download_document(
                bucket_name=minio_client.default_bucket,
                object_name=parsed_text_object,
            )
            return content
        except Exception:
            self.logger.warning(
                "解析全文下载失败",
                document_id=document_id,
                object_name=parsed_text_object,
            )
            return None

    async def get_document_frames(self, document_id: int) -> dict:
        """获取文档视频帧预签名 URL 列表。

        读取 document.storage["frames"] 中的 MinIO 路径列表，
        为每个帧生成预签名 URL。非视频文档或无帧数据时返回空列表。

        Args:
            document_id: 文档 ID

        Returns:
            {"frames": [{"index": 0, "url": "..."}, ...], "total": N}
        """
        from novamind.shared.storage.client_factory import ClientFactory

        document = await self.doc_repo.get_by_id(document_id)
        if not document:
            return {"frames": [], "total": 0}

        storage_info = document.get_storage_info()
        frame_paths = storage_info.get("frames", [])
        if not frame_paths:
            return {"frames": [], "total": 0}

        try:
            minio_client = await ClientFactory.get_minio_client()
            frames = []
            for idx, path in enumerate(frame_paths):
                if not path:
                    continue
                url = await minio_client.get_file_url(
                    bucket_name=minio_client.default_bucket,
                    object_name=path,
                    expires=3600,
                )
                frames.append({"index": idx, "url": url})

            return {"frames": frames, "total": len(frames)}
        except Exception:
            self.logger.warning(
                "视频帧预签名 URL 生成失败",
                document_id=document_id,
            )
            return {"frames": [], "total": 0}
