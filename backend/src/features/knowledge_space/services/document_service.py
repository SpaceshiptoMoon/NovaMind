"""
文档管理服务

处理文档的上传、处理、删除等操作
支持多租户和知识库层级
使用 MinIO 对象存储和 Elasticsearch 向量检索

注意: 分块数据仅存储在 Elasticsearch 中，不在 MySQL 中存储
"""

from typing import Optional, List, Dict, Any
import hashlib
import asyncio
import tempfile
from src.shared.utils.time_utils import now_china
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from src.features.knowledge_space.models.document import Document, DocumentStatus
from src.features.knowledge_space.models.knowledge_base import KnowledgeBase
from src.features.knowledge_space.models.knowledge_space import KnowledgeSpace
from src.features.knowledge_space.repository.document_repository import DocumentRepository
from src.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
from src.features.knowledge_space.repository.member_repository import MemberRepository
from src.features.knowledge_space.repository.space_repository import SpaceRepository
from src.features.knowledge_space.services.permission_service import PermissionService
from src.features.knowledge_space.api.exceptions import (
    KnowledgeBaseNotFoundError,
    DocumentNotFoundError,
    DocumentAlreadyExistsError,
    DocumentInvalidTypeError,
    DocumentSizeExceededError,
    DocumentProcessingError,
    DocumentAlreadyProcessingError,
    InvalidParameterError,
    KnowledgeSpaceError,
    KnowledgeBaseAccessDeniedError,
    SpaceAccessDeniedError,
)
from src.shared.storage.minio_client import MinioClient
from src.shared.storage.elasticsearch_client import ElasticsearchClient
from src.shared.utils.document_readers.document_loader import DocumentProcessor
from src.shared.utils.file_validator import validate_file, FileInfo
from src.shared.ai_models.embedding import OpenAICompatibleEmbedding as EmbeddingClient
from src.setting.yaml_config import get_config
from src.core.middleware.structured_logging import get_logger


def _compute_sha256(content: bytes) -> str:
    """计算 SHA256 哈希（CPU 密集操作，用于在线程池中执行）"""
    return hashlib.sha256(content).hexdigest()


DEFAULT_CHUNK_SIZE = 2000
DEFAULT_CHUNK_OVERLAP = 50
DEFAULT_MIN_CHUNK_SIZE = 500
DEFAULT_EMBEDDING_BATCH_SIZE = 32


class DocumentCancelledError(Exception):
    """文档处理被用户取消"""


async def _check_document_cancelled(document_id: int) -> None:
    """
    检查文档是否被取消，是则抛出 DocumentCancelledError

    在 pipeline 关键节点调用，实现提前终止。
    """
    from src.shared.mq.task_tracker import is_document_cancelled
    if await is_document_cancelled(document_id):
        raise DocumentCancelledError(f"文档 {document_id} 处理已被用户取消")


class DocumentService:
    """
    文档管理服务

    处理文档的完整生命周期：上传 → 处理 → 分块 → 向量化 → ES 索引
    支持多租户和知识库层级
    """

    # 文件大小限制（默认 100MB）
    MAX_FILE_SIZE = 100 * 1024 * 1024

    # 支持的文件类型
    SUPPORTED_FILE_TYPES = ["pdf", "docx", "doc", "txt", "md", "csv", "xlsx", "xls", "pptx", "ppt", "html", "json", "jpg", "jpeg", "png", "gif", "webp"]

    # 图片文件类型
    IMAGE_FILE_TYPES = frozenset({"jpg", "jpeg", "png", "gif", "webp"})

    def __init__(
        self,
        session: AsyncSession,
        minio_client: MinioClient,
        es_client: ElasticsearchClient,
    ):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.kb_repo = KnowledgeBaseRepository(session)
        self.space_repo = SpaceRepository(session)
        self.minio_client = minio_client
        self.es_client = es_client
        self.logger = get_logger(__name__)
        self.member_repo = MemberRepository(session)
        self.permission_service = PermissionService()

    async def count_kb_documents(
        self,
        kb_id: int,
        status: Optional[DocumentStatus] = None,
    ) -> int:
        """统计知识库中的文档数量"""
        return await self.doc_repo.count_by_kb(kb_id=kb_id, status=status)

    async def upload_document(
        self,
        kb_id: int,
        uploader_id: int,
        file_content: bytes,
        filename: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Document:
        """
        上传文档（仅存 MinIO，不触发解析）

        Args:
            kb_id: 知识库 ID
            uploader_id: 上传者 ID
            file_content: 文件内容
            filename: 文件名
            metadata: 文档元数据

        Returns:
            创建的文档记录

        Raises:
            KnowledgeBaseNotFoundError: 知识库不存在
            DocumentAlreadyExistsError: 文档已存在
            DocumentInvalidTypeError: 不支持的文件类型
            DocumentSizeExceededError: 文件大小超限
            InvalidParameterError: 参数无效
        """
        # 1. 参数校验
        if not filename or not filename.strip():
            raise InvalidParameterError("文件名不能为空", field="filename")

        # 2. 检查知识库是否存在
        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb:
            raise KnowledgeBaseNotFoundError(kb_id)

        # 3. 权限检查：上传者必须是空间成员且拥有 EDITOR 及以上角色
        member = await self.member_repo.get_by_space_and_user(kb.space_id, uploader_id)
        if not member or not member.is_active():
            raise SpaceAccessDeniedError(kb.space_id, uploader_id, "无权在此知识库上传文档")
        if not self.permission_service.can_upload_document(member):
            raise SpaceAccessDeniedError(kb.space_id, uploader_id, "需要编辑者或更高权限才能上传文档")

        # 4. 获取允许的文件类型
        allowed_types = self._get_allowed_file_types(kb)

        # 5. 验证文件（使用 python-magic 检测真实 MIME 类型）
        file_info = validate_file(
            content=file_content,
            filename=filename,
            allowed_extensions=allowed_types,
        )

        if not file_info.is_valid:
            self.logger.warning(
                "文件验证失败",
                filename=filename,
                extension=file_info.extension,
                detected_mime=file_info.detected_mime,
                message=file_info.validation_message,
            )
            raise DocumentInvalidTypeError(
                f"{file_info.extension}: {file_info.validation_message}"
            )

        # 5.5 根据空间类型校验文件类型
        file_type = file_info.extension
        space = await self.space_repo.get_by_id(kb.space_id)
        space_type = space.space_type if space else "text"

        if space_type == "text" and file_type in self.IMAGE_FILE_TYPES:
            raise DocumentInvalidTypeError(
                f"{file_type}: 该空间为文本类型，只能上传文本文档。请在空间设置中将类型切换为多模态"
            )
        if space_type == "multimodal" and file_type not in self.IMAGE_FILE_TYPES:
            raise DocumentInvalidTypeError(
                f"{file_type}: 该空间为多模态类型，只能上传图片文件。"
            )

        # 6. 检查文件大小
        file_size = len(file_content)
        max_size = self._get_max_file_size(kb)
        if file_size > max_size:
            raise DocumentSizeExceededError(file_size, max_size)

        # 7. 计算文件哈希（CPU 密集操作放入线程池）
        file_hash = await asyncio.to_thread(_compute_sha256, file_content)
        file_type = file_info.extension

        # 8. 检查重复（同知识库内活跃文档）
        existing = await self.doc_repo.get_by_hash(kb_id, file_hash)
        if existing:
            raise DocumentAlreadyExistsError(filename)

        # 8.1 检查是否有同 hash 的已软删除文档（可复用记录）
        soft_deleted = await self.doc_repo.get_deleted_by_hash(kb_id, file_hash)
        if soft_deleted:
            soft_deleted.revive(uploader_id=uploader_id, filename=filename)

            # 重新上传 MinIO（软删除时文件已被清理）
            minio_result = await self.minio_client.upload_document(
                space_id=kb.space_id,
                kb_id=kb_id,
                document_id=soft_deleted.id,
                file_data=file_content,
                filename=filename,
                file_hash=file_hash,
            )
            soft_deleted.set_minio_info(
                bucket=minio_result["bucket"],
                object_name=minio_result["object_name"],
                etag=minio_result.get("etag"),
            )

            # 更新 hash 缓存（该 hash 现在又有活跃文档了）
            await self.doc_repo.cache_document_hash(kb_id, file_hash, exists=True)

            await self.session.commit()

            self.logger.info(
                "复活已删除文档",
                document_id=soft_deleted.id,
                kb_id=kb_id,
                uploader_id=uploader_id,
            )
            return soft_deleted

        # 9. 创建文档记录 + 上传 MinIO（使用 SAVEPOINT 保证原子性）
        async with self.db.begin_nested():
            # 创建文档记录（先获取 document_id）
            document = await self.doc_repo.create({
                "space_id": kb.space_id,
                "kb_id": kb_id,
                "uploader_id": uploader_id,
                "filename": filename,
                "file_type": file_type,
                "file_size": file_size,
                "file_hash": file_hash,
                "storage": {},  # 临时空值，上传后更新
                "status": DocumentStatus.UPLOADED,
            })

            # 使用真实 document_id 上传到 MinIO
            minio_result = await self.minio_client.upload_document(
                space_id=kb.space_id,
                kb_id=kb_id,
                document_id=document.id,
                file_data=file_content,
                filename=filename,
                file_hash=file_hash,
            )

            # 更新文档记录中的存储信息
            document.set_minio_info(
                bucket=minio_result["bucket"],
                object_name=minio_result["object_name"],
                etag=minio_result.get("etag"),
            )

        await self.session.commit()

        self.logger.info(
            "文档上传成功，等待拆分解析",
            document_id=document.id,
            kb_id=kb_id,
            filename=filename,
            uploader_id=uploader_id,
        )

        return document

    async def upload_documents(
        self,
        kb_id: int,
        uploader_id: int,
        files: List[tuple],
    ) -> dict:
        """
        批量上传文档（仅存 MinIO，不触发解析）

        单个文件失败不影响其他文件。

        Args:
            kb_id: 知识库 ID
            uploader_id: 上传者 ID
            files: [(filename, file_content), ...] 文件列表

        Returns:
            {"success": [Document, ...], "failed": [{"filename": str, "error": str}, ...]}
        """
        success: List[Document] = []
        failed: List[dict] = []

        for filename, file_content in files:
            try:
                doc = await self.upload_document(
                    kb_id=kb_id,
                    uploader_id=uploader_id,
                    file_content=file_content,
                    filename=filename,
                )
                success.append(doc)
            except Exception as e:
                self.logger.warning(
                    "批量上传：单个文件上传失败",
                    filename=filename,
                    error=str(e),
                )
                failed.append({"filename": filename, "error": str(e)})

        self.logger.info(
            "批量上传完成",
            total=len(files),
            success_count=len(success),
            failed_count=len(failed),
            kb_id=kb_id,
            uploader_id=uploader_id,
        )

        return {"success": success, "failed": failed}

    @staticmethod
    async def execute_document_pipeline(
        session: AsyncSession,
        document_id: int,
        kb_id: int,
        space_id: int,
        file_content: bytes,
        filename: str,
    ) -> None:
        """
        执行文档处理的核心 pipeline（独立函数，可被 arq worker 或直接调用）

        Args:
            session: 数据库会话
            document_id: 文档 ID
            kb_id: 知识库 ID
            space_id: 空间 ID
            file_content: 文件内容
            filename: 文件名
        """
        _logger = get_logger(__name__)
        doc_repo = DocumentRepository(session)
        kb_repo = KnowledgeBaseRepository(session)

        document = await doc_repo.get_by_id(document_id)
        if not document:
            return

        kb = await kb_repo.get_by_id(document.kb_id)
        if not kb:
            return

        # ===== 图片文档分支 =====
        file_ext = document.file_type.lower() if document.file_type else ""

        if file_ext in DocumentService.IMAGE_FILE_TYPES:
            await _process_image_document_static(
                document, file_content, session, _logger
            )
            return

        # ===== 文本文档分支（现有逻辑）=====
        # 获取空间配置（提前获取，语义切分和向量化都依赖）
        space = await session.get(KnowledgeSpace, document.space_id)
        embedding_model_name = space.embedding_model if space else None
        space_owner_id = space.owner_id if space else None

        # 获取 DocumentProcessor（传入空间配置的嵌入模型，确保语义切分使用正确模型）
        processor = await _get_document_processor_static(session, user_id=space_owner_id, model_name=embedding_model_name)
        splitting_config = kb.get_splitting_config()
        strategy = splitting_config.get("strategy", "recursive")

        suffix = f".{document.file_type}"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        try:
            split_docs = await processor.load_with_strategy(
                file_path=tmp_path,
                strategy=strategy,
                chunk_size=splitting_config.get("chunk_size", DEFAULT_CHUNK_SIZE),
                chunk_overlap=splitting_config.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP),
                min_chunk_size=splitting_config.get("min_chunk_size", DEFAULT_MIN_CHUNK_SIZE),
                max_chunk_size=splitting_config.get("max_chunk_size", 2000),
                similarity_threshold=splitting_config.get("similarity_threshold", 0.7),
                batch_size=splitting_config.get("batch_size", 20),
            )
            chunks = [doc.get("text", "") or doc.get("content", "") for doc in split_docs]
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # 检查点 1：文档解析完成之后
        await _check_document_cancelled(document_id)

        # 2. 准备 ES 数据
        es_chunks = _prepare_es_chunks_static(document, chunks)

        # 3. 向量化并索引到 ES（Embedding 配置从空间级别读取）
        embedding_config = space.embedding_config if space and space.embedding_config else {}
        embeddings = await _generate_embeddings_static(
            [c["content"] for c in es_chunks],
            embedding_config,
            session=session,
            user_id=space_owner_id,
        )

        for i, embedding in enumerate(embeddings):
            es_chunks[i]["embedding"] = embedding

        # 检查点 2：向量化完成之后
        await _check_document_cancelled(document_id)

        # 5. 生成假设问题（由知识库配置控制）
        kb_config = kb.get_config() or {}
        qg_config = kb_config.get("question_generation", {})
        should_generate = qg_config.get("enabled", False) if qg_config else False

        if should_generate:
            try:
                import asyncio
                chunk_count = len(es_chunks)
                _logger.info(
                    "假设问题生成开始",
                    document_id=document_id,
                    chunk_count=chunk_count,
                )
                # 不使用全局超时：generate_questions_batch 内部每批次有 120s 超时，
                # 失败的批次跳过（保留空结果），成功的批次保留问题。
                # 这样即使部分批次超时，已生成的结果不会丢失。
                questions_list, question_embeddings_list = await _generate_questions_for_chunks_static(
                    chunks=[c["content"] for c in es_chunks],
                    document_title=document.filename,
                    kb_config=kb_config,
                    embedding_config=embedding_config,
                    user_id=document.uploader_id,
                    session=session,
                )
                for i, (questions, q_embeddings) in enumerate(zip(questions_list, question_embeddings_list)):
                    es_chunks[i]["questions"] = questions
                    es_chunks[i]["question_embeddings"] = [
                        {"vector": emb} for emb in q_embeddings
                    ]
                _logger.info(
                    "假设问题生成完成",
                    document_id=document_id,
                    total_questions=sum(len(q) for q in questions_list),
                )
            except Exception as e:
                _logger.warning(
                    "假设问题生成失败，跳过继续处理",
                    document_id=document_id,
                    error=str(e),
                )
                for chunk in es_chunks:
                    chunk["questions"] = []
                    chunk["question_embeddings"] = []
                    chunk["question_embeddings"] = []
                    chunk["question_embeddings"] = []
        else:
            for chunk in es_chunks:
                chunk["questions"] = []
                chunk["question_embeddings"] = []

        # 检查点 3：问题生成完成之后
        await _check_document_cancelled(document_id)

        # 检查点 4：ES 索引写入之前
        await _check_document_cancelled(document_id)

        es_client = await _get_es_client_static()
        indexed_count = await es_client.bulk_index_chunks(
            space_id=document.space_id,
            chunks=es_chunks,
            embedding_dim=embedding_config.get("dimension"),
        )

        if indexed_count == 0 and len(es_chunks) > 0:
            raise DocumentProcessingError(
                document_id=document_id,
                error_message=f"ES 索引写入失败，共 {len(es_chunks)} 个分块均未成功写入",
            )

        # 5. 标记文档完成
        document.mark_completed()
        document.doc_metadata = {
            **(document.doc_metadata or {}),
            "chunk_count": len(chunks),
            "total_tokens": sum(len(c.split()) for c in chunks),
            "split_strategy": splitting_config.get("strategy", "recursive"),
            "chunk_size": splitting_config.get("chunk_size", DEFAULT_CHUNK_SIZE),
            "chunk_overlap": splitting_config.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP),
            "indexed_at": now_china().isoformat(),
        }
        await session.commit()

        _logger.info(
            "文档处理完成",
            document_id=document_id,
            chunk_count=len(chunks),
        )


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

        # 2.5 PROCESSING 状态拒绝删除
        if document.status == DocumentStatus.PROCESSING:
            raise DocumentAlreadyProcessingError(document_id)

        # 3. 细粒度权限检查：EDITOR 只能删除自己的文档，ADMIN 可删除任意文档
        if not self.permission_service.can_delete_any_document(member):
            if document.uploader_id != user_id:
                raise SpaceAccessDeniedError(
                    kb.space_id, user_id,
                    "只能删除自己上传的文档，删除他人文档需要管理员权限",
                )

        # 4. 删除文档记录（先数据库操作，确保事务一致性）
        await self.doc_repo.delete(document_id)

        # 5. 更新知识库统计（使用行锁保证原子性）
        await self.session.commit()

        # 6. 失效该知识库的搜索缓存
        try:
            from src.shared.cache.redis_client import get_redis_client
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
            self.logger.warning("删除 ES 分块数据失败（数据已从 DB 删除）", document_id=document_id, error=str(e))

        try:
            storage_info = document.get_storage_info()
            if storage_info.get("minio_bucket") and storage_info.get("minio_object_name"):
                await self.minio_client.delete_document(
                    bucket_name=storage_info["minio_bucket"],
                    object_name=storage_info["minio_object_name"],
                )
        except Exception as e:
            self.logger.warning("删除 MinIO 文件失败（数据已从 DB 删除）", document_id=document_id, error=str(e))

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
        status: Optional[DocumentStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Document]:
        """
        获取知识库的文档列表

        Args:
            kb_id: 知识库 ID
            status: 状态过滤
            skip: 跳过数量
            limit: 返回数量

        Returns:
            文档列表
        """
        return await self.doc_repo.get_by_kb(
            kb_id=kb_id,
            status=status,
            skip=skip,
            limit=limit,
        )

    async def get_document_chunks(
        self,
        space_id: int,
        document_id: int,
        skip: int = 0,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        获取文档的分块列表（从 Elasticsearch 获取）

        Args:
            space_id: 空间 ID
            document_id: 文档 ID
            skip: 跳过的记录数
            limit: 返回的最大记录数

        Returns:
            分块列表
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

    def _get_file_type(self, filename: str) -> str:
        """
        获取文件类型并验证文件名安全性

        Args:
            filename: 文件名

        Returns:
            文件扩展名

        Raises:
            InvalidParameterError: 文件名包含非法字符或路径遍历
            DocumentInvalidTypeError: 不支持的文件类型
        """
        import re
        from pathlib import Path

        # 检查文件名是否为空
        if not filename or not filename.strip():
            raise InvalidParameterError("文件名不能为空", field="filename")

        # 防止路径遍历攻击
        # 只允许字母、数字、中文、下划线、连字符、空格和点
        if not re.match(r'^[\w一-龥\-\s\.]+$', filename):
            raise InvalidParameterError("文件名包含非法字符", field="filename")

        # 检查路径遍历
        if '..' in filename or '/' in filename or '\\' in filename:
            raise InvalidParameterError("文件名包含非法路径字符", field="filename")

        # 获取扩展名
        ext = Path(filename).suffix.lower().lstrip('.')

        # 检查是否为支持的文件类型
        if ext not in self.SUPPORTED_FILE_TYPES:
            raise DocumentInvalidTypeError(ext)

        return ext

    def _get_max_file_size(self, kb: KnowledgeBase) -> int:
        """获取最大文件大小限制"""
        config = kb.get_config()
        limits = config.get("limits", {})
        max_size_mb = limits.get("max_file_size_mb", 100)
        return max_size_mb * 1024 * 1024

    def _get_allowed_file_types(self, kb: KnowledgeBase) -> List[str]:
        """获取允许的文件类型"""
        config = kb.get_config()
        limits = config.get("limits", {})
        return limits.get("allowed_file_types", self.SUPPORTED_FILE_TYPES)

    # ========== 任务状态管理方法 ==========

    async def get_processing_status(self, document_id: int) -> str:
        """
        获取文档处理状态

        Args:
            document_id: 文档 ID

        Returns:
            状态字符串: "queued" | "in_progress" | "not_found"
        """
        from src.shared.mq.task_tracker import get_job_id_for_document
        from src.shared.mq import get_arq_pool

        job_id = await get_job_id_for_document(document_id)
        if not job_id:
            return "not_found"

        try:
            pool = await get_arq_pool()
            job_info = await pool.job_info(job_id)
            if not job_info:
                return "not_found"
            # job_info 存在说明任务还在队列中或正在执行
            return "in_progress"
        except Exception as e:
            self.logger.warning("获取处理状态失败", error=str(e))
            return "not_found"

    async def cancel_processing(self, document_id: int) -> bool:
        """
        取消文档处理任务

        通过 Redis 取消标记通知正在运行的 pipeline 终止，
        同时尝试通过 arq abort 取消排队中的任务。

        Args:
            document_id: 文档 ID

        Returns:
            是否成功发送取消信号

        Raises:
            DocumentNotFoundError: 文档不存在
            InvalidParameterError: 文档不在处理中状态
        """
        document = await self.doc_repo.get_by_id(document_id)
        if not document:
            raise DocumentNotFoundError(document_id)
        if document.status != DocumentStatus.PROCESSING:
            raise InvalidParameterError("只能取消处理中的文档", field="document_id")

        from src.shared.mq.task_tracker import (
            get_job_id_for_document, mark_document_cancelled,
        )
        from src.shared.mq import get_arq_pool

        # 设置取消标记（pipeline 会在检查点检测到）
        await mark_document_cancelled(document_id)

        job_id = await get_job_id_for_document(document_id)
        if job_id:
            try:
                pool = await get_arq_pool()
                await pool.abort_job(job_id)
            except Exception as e:
                self.logger.warning("arq abort 失败（取消标记已设置）", document_id=document_id, error=str(e))

        self.logger.info("文档取消信号已发送", document_id=document_id, job_id=job_id)
        return True

    async def get_active_processing_count(self) -> int:
        """
        获取正在处理的文档数量

        Returns:
            正在处理的数量
        """
        from src.shared.mq.task_tracker import get_active_document_count
        return await get_active_document_count()

    # ========== 拆分解析方法 ==========

    async def process_document(
        self,
        document_id: int,
    ) -> Document:
        """
        触发单文档拆分解析。
        校验状态 → 从 MinIO 下载 → 异步处理。

        Args:
            document_id: 文档 ID

        Returns:
            文档对象

        Raises:
            DocumentNotFoundError: 文档不存在
            DocumentAlreadyProcessingError: 文档正在处理中
            KnowledgeBaseNotFoundError: 知识库不存在
        """
        document = await self._validate_document_not_processing(document_id)

        # COMPLETED 文档需要走 reprocess 流程
        if document.status == DocumentStatus.COMPLETED:
            raise InvalidParameterError(
                "文档已完成处理，如需重新解析请使用 reprocess 接口",
                field="document_id",
            )

        # UPLOADED 或 FAILED 状态允许处理
        kb = await self.kb_repo.get_by_id(document.kb_id)
        if not kb:
            raise KnowledgeBaseNotFoundError(document.kb_id)

        if not kb.is_active():
            raise KnowledgeBaseNotFoundError(document.kb_id)

        await self._enqueue_document_processing(document, "处理")
        return document

    async def process_kb_documents(
        self,
        kb_id: int,
        document_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        批量触发文档拆分解析。
        单文档失败不影响其他文档。

        Args:
            kb_id: 知识库 ID
            document_ids: 文档 ID 列表，为空则处理全部 UPLOADED 文档

        Returns:
            批量处理结果
        """
        results = []

        # 如果未指定 document_ids，查询所有 UPLOADED 状态的文档
        if not document_ids:
            documents = await self.doc_repo.get_by_kb(kb_id, status=DocumentStatus.UPLOADED)
            document_ids = [doc.id for doc in documents]

        for doc_id in document_ids:
            try:
                await self.process_document(doc_id)
                results.append({
                    "document_id": doc_id,
                    "status": "processing",
                    "message": "已触发处理",
                })
            except DocumentAlreadyProcessingError:
                results.append({
                    "document_id": doc_id,
                    "status": "skipped",
                    "message": "文档正在处理中，跳过",
                })
            except (DocumentNotFoundError, InvalidParameterError) as e:
                results.append({
                    "document_id": doc_id,
                    "status": "failed",
                    "message": str(e),
                })

        return {
            "total": len(results),
            "success": sum(1 for r in results if r["status"] == "processing"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "skipped": sum(1 for r in results if r["status"] == "skipped"),
            "results": results,
        }

    async def reprocess_document(
        self,
        document_id: int,
    ) -> Document:
        """
        重新解析文档（清除旧 chunk，按当前 config 重新切分）

        Args:
            document_id: 文档 ID

        Returns:
            文档对象

        Raises:
            DocumentNotFoundError: 文档不存在
            DocumentAlreadyProcessingError: 文档正在处理中
        """
        document = await self._validate_document_not_processing(document_id)

        # 清除 ES 旧分块 + 重置状态
        await self._reset_document_to_uploaded(document, "重新解析")

        await self._enqueue_document_processing(document, "重新解析")
        return document

    async def retry_document(
        self,
        document_id: int,
    ) -> Document:
        """
        重试文档处理（支持 FAILED 和 COMPLETED 状态）

        先删除 ES 中的旧分块数据保证唯一性，再重新入队处理。
        对于 PROCESSING 状态的文档，应先使用 cancel_processing 取消。

        Args:
            document_id: 文档 ID

        Returns:
            文档对象

        Raises:
            DocumentNotFoundError: 文档不存在
            DocumentAlreadyProcessingError: 文档正在处理中
            InvalidParameterError: 文档状态不允许重试
        """
        document = await self._validate_document_not_processing(document_id)

        if document.status not in (DocumentStatus.FAILED, DocumentStatus.COMPLETED):
            raise InvalidParameterError(
                "只能重试失败或已完成的文档",
                field="document_id",
            )

        previous_status = document.status
        await self._reset_document_to_uploaded(document, "重试")
        await self._enqueue_document_processing(document, "重试")

        self.logger.info(
            "文档重试已入队",
            document_id=document_id,
            previous_status=previous_status,
        )
        return document

    # ---------- 文档处理共享辅助方法 ----------

    async def _validate_document_not_processing(self, document_id: int) -> Document:
        """获取文档并验证不在处理中"""
        document = await self.doc_repo.get_by_id(document_id)
        if not document:
            raise DocumentNotFoundError(document_id)
        if document.status == DocumentStatus.PROCESSING:
            raise DocumentAlreadyProcessingError(document_id)
        return document

    async def _enqueue_document_processing(self, document: Document, log_label: str = "处理"):
        """检查活跃任务并入队文档处理"""
        from src.shared.mq.task_tracker import is_document_actively_processing
        if await is_document_actively_processing(document.id):
            raise DocumentAlreadyProcessingError(document.id)

        from src.shared.mq import enqueue_process_document
        await enqueue_process_document(
            document_id=document.id,
            kb_id=document.kb_id,
            space_id=document.space_id,
        )
        self.logger.info(f"文档{log_label}已入队", document_id=document.id)

    async def _reset_document_to_uploaded(self, document: Document, log_label: str = "重置"):
        """清除 ES 旧分块并重置文档状态为 UPLOADED"""
        try:
            await self.es_client.delete_document_chunks(
                space_id=document.space_id,
                document_id=document.id,
            )
            self.logger.info(f"{log_label}前已清除 ES 旧分块", document_id=document.id)
        except Exception as e:
            self.logger.warning("清除 ES 旧分块失败", document_id=document.id, error=str(e))

        document.status = DocumentStatus.UPLOADED
        document.status_info = {}
        await self.session.commit()


# ========== 模块级静态辅助函数 ==========


async def _process_image_document_static(
    document: Document,
    file_content: bytes,
    session,
    _logger,
):
    """处理图片类型文档：生成多模态嵌入向量并索引到 ES

    支持两种模式：
    - VLM 关闭：仅生成 image_embedding，content 不写入，仅支持以图搜图
    - VLM 开启：额外调用视觉模型生成描述文本 + text embedding，支持 BM25 + 文本向量 + 以图搜图
    """
    from src.shared.ai_models.embedding import BaseMultimodalEmbedding

    # 1. 读取空间配置（统一从 config.embedding 读取）
    space = await session.get(KnowledgeSpace, document.space_id)
    if not space:
        return
    space_config = space.get_config()
    embedding_config = space_config.get("embedding") or {}
    model_name = embedding_config.get("model")
    mm_dim = embedding_config.get("dimension")

    if not model_name:
        raise DocumentProcessingError(
            document_id=document.id,
            error_message="该空间未配置嵌入模型，无法处理图片文件",
        )

    # 检查 VLM 描述开关（从知识库的解析配置读取）
    kb_repo = KnowledgeBaseRepository(session)
    kb = await kb_repo.get_by_id(document.kb_id)
    vlm_enabled = False
    if kb:
        kb_config = kb.get_config() or {}
        parsing_config = kb_config.get("parsing", {})
        vlm_enabled = parsing_config.get("vlm_description_enabled", False)

    # 检查点 0：配置读取后
    await _check_document_cancelled(document.id)

    # 2. 获取多模态嵌入客户端
    from src.features.user.services.model_config_service import ModelConfigService
    mcs = ModelConfigService(session)
    client = await mcs.get_multimodal_embedding_client_by_model(document.uploader_id, model_name)

    if not isinstance(client, BaseMultimodalEmbedding):
        raise DocumentProcessingError(
            document_id=document.id,
            error_message=f"模型 {model_name} 不支持图片嵌入",
        )

    # 3. 生成图片嵌入向量（始终执行，不受 VLM 开关影响）
    image_vector = await client.generate_image_embedding(file_content)

    # 检查点 1：向量化完成后
    await _check_document_cancelled(document.id)

    # 4. VLM 图片描述（如果启用）
    description_text = ""
    text_vector = None

    if vlm_enabled:
        try:
            description_text = await _generate_image_description(
                file_content=file_content,
                document=document,
                mcs=mcs,
                _logger=_logger,
            )

            if description_text:
                # 生成描述文本的向量
                text_vector = await _generate_single_embedding_static(
                    text=description_text,
                    embedding_config=embedding_config,
                    session=session,
                    user_id=document.uploader_id,
                )

                _logger.info(
                    "VLM 图片描述生成成功",
                    document_id=document.id,
                    description_length=len(description_text),
                    has_text_vector=text_vector is not None,
                )

        except Exception as e:
            _logger.warning(
                "VLM 图片描述生成失败，跳过描述文本（不影响 image_embedding）",
                document_id=document.id,
                error=str(e),
            )
            description_text = ""
            text_vector = None

    # 5. 构建 ES chunk
    storage_info = document.storage or {}
    storage_path = storage_info.get("minio_object_name", "")

    es_chunk = {
        "space_id": document.space_id,
        "kb_id": document.kb_id,
        "document_id": document.id,
        "chunk_id": f"{document.id}_0",
        "chunk_index": 0,
        "chunk_type": "image",
        "image_embedding": image_vector,
        "image_url": storage_path,
        "file_info": {
            "filename": document.filename,
            "file_type": document.file_type,
        },
        "metadata": {
            "content_hash": document.file_hash,
        },
    }

    # VLM 开启且有描述时才写入 content 和 embedding
    if description_text:
        es_chunk["content"] = description_text

    # VLM 开启且描述文本存在时，额外写入 embedding 字段
    if description_text and text_vector:
        es_chunk["embedding"] = text_vector

    # 检查点 2：ES 写入前
    await _check_document_cancelled(document.id)

    # 6. 索引到 ES
    es_client = await _get_es_client_static()
    indexed_count = await es_client.bulk_index_chunks(
        space_id=document.space_id,
        chunks=[es_chunk],
        embedding_dim=mm_dim,
        multimodal_dim=mm_dim,
    )

    if indexed_count == 0:
        raise DocumentProcessingError(
            document_id=document.id,
            error_message="ES 索引写入失败",
        )

    # 7. 标记文档完成
    document.mark_completed()
    doc_meta = {
        **(document.doc_metadata or {}),
        "chunk_count": 1,
        "indexed_at": now_china().isoformat(),
        "chunk_type": "image",
    }
    if vlm_enabled and description_text:
        doc_meta["vlm_description"] = True
        doc_meta["description_length"] = len(description_text)
    document.doc_metadata = doc_meta
    await session.commit()

    _logger.info(
        "图片文档处理完成",
        document_id=document.id,
        model=model_name,
        vector_dim=len(image_vector),
        vlm_enabled=vlm_enabled,
        has_description=bool(description_text),
    )


def _prepare_es_chunks_static(document: Document, chunks: List[str]) -> List[Dict[str, Any]]:
    """
    将文本分块列表转换为 ES 索引格式的字典列表

    Args:
        document: 文档对象
        chunks: 文本分块列表

    Returns:
        ES 索引格式的分块字典列表
    """
    es_chunks = []
    for i, chunk_text in enumerate(chunks):
        chunk_data = {
            "space_id": document.space_id,
            "kb_id": document.kb_id,
            "document_id": document.id,
            "chunk_id": f"{document.id}_{i}",
            "chunk_index": i,
            "content": chunk_text,
            "chunk_type": "text",
            "questions": [],
            "question_embeddings": [],
        }
        es_chunks.append(chunk_data)
    return es_chunks


async def _get_es_client_static() -> ElasticsearchClient:
    """获取 ES 客户端（静态方法用）"""
    from src.shared.clients import ClientFactory
    return await ClientFactory.get_elasticsearch_client()


async def _get_document_processor_static(session: AsyncSession, user_id: Optional[int] = None, model_name: Optional[str] = None) -> DocumentProcessor:
    """获取文档处理器（静态方法用）"""
    from src.features.user.services.model_config_service import ModelConfigService

    model_config_service = ModelConfigService(session)
    if not model_name and user_id:
        model_name = await model_config_service.get_user_default_model_name(user_id, "embedding")
    if not model_name:
        raise DocumentProcessingError(
            document_id=0,
            error_message="未配置 Embedding 模型，请在模型配置中添加",
        )
    effective_user_id = user_id or 0
    embedding_client = await model_config_service.get_embedding_client_by_model(
        user_id=effective_user_id, model=model_name
    )
    return DocumentProcessor(embedding_client=embedding_client)


async def _generate_embeddings_static(
    texts: List[str],
    embedding_config: Dict[str, Any],
    session: Optional[AsyncSession] = None,
    user_id: Optional[int] = None,
) -> List[List[float]]:
    """生成文本向量（静态方法用）"""
    if not session:
        raise DocumentProcessingError(document_id=0, error_message="生成向量需要数据库会话")

    model_name = embedding_config.get("model")
    embedding_client = await _get_embedding_client_static(session, user_id, model_name)

    batch_size = embedding_config.get("batch_size", DEFAULT_EMBEDDING_BATCH_SIZE)
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        embeddings = await embedding_client.generate_embeddings_batch(batch)
        all_embeddings.extend(embeddings)
    return all_embeddings


async def _get_embedding_client_static(
    session: AsyncSession,
    user_id: Optional[int] = None,
    model_name: Optional[str] = None,
) -> EmbeddingClient:
    """获取 Embedding 客户端（静态方法用）"""
    from src.features.user.services.model_config_service import ModelConfigService

    model_config_service = ModelConfigService(session)
    if not model_name and user_id:
        model_name = await model_config_service.get_user_default_model_name(user_id, "embedding")
    if not model_name:
        raise DocumentProcessingError(
            document_id=0,
            error_message="未配置 Embedding 模型，请在模型配置中添加",
        )
    effective_user_id = user_id or 0
    return await model_config_service.get_embedding_client_by_model(
        user_id=effective_user_id, model=model_name
    )


async def _generate_single_embedding_static(
    text: str,
    embedding_config: Dict[str, Any],
    session: AsyncSession,
    user_id: Optional[int] = None,
) -> Optional[List[float]]:
    """生成单条文本的嵌入向量（用于 VLM 描述文本）

    Args:
        text: 文本内容
        embedding_config: 嵌入模型配置（含 model 名称）
        session: 数据库会话
        user_id: 用户 ID

    Returns:
        嵌入向量，失败返回 None
    """
    try:
        model_name = embedding_config.get("model")
        embedding_client = await _get_embedding_client_static(session, user_id, model_name)
        embeddings = await embedding_client.generate_embeddings_batch([text])
        return embeddings[0] if embeddings else None
    except Exception as e:
        _log = get_logger(__name__)
        _log.warning("单条文本嵌入生成失败", error=str(e))
        return None


async def _generate_image_description(
    file_content: bytes,
    document: Document,
    mcs,  # ModelConfigService
    _logger,
) -> str:
    """调用 VLM 生成图片描述文本

    Args:
        file_content: 图片二进制内容
        document: 文档对象
        mcs: ModelConfigService 实例
        _logger: 日志器

    Returns:
        描述文本（截断到 2000 字符），失败抛异常由调用方处理
    """
    import base64
    from src.shared.prompts.templates import PromptManager, PromptTemplate

    # 1. 获取 VLM 客户端
    vlm_model = await mcs.get_user_default_model_name(document.uploader_id, "vlm")
    if not vlm_model:
        raise ValueError("未配置 VLM 模型，请在模型配置中添加视觉模型")

    vlm_client = await mcs.get_vlm_client_by_model(document.uploader_id, vlm_model)

    # 2. 构建 base64 图片
    file_ext = (document.file_type or "png").lower()
    mime_type = f"image/{file_ext}" if file_ext != "jpg" else "image/jpeg"
    base64_data = base64.b64encode(file_content).decode("utf-8")

    # 3. 获取描述 Prompt
    description_prompt = PromptManager.get_template(PromptTemplate.IMAGE_DESCRIPTION.value)

    # 4. 构建多模态消息（OpenAI 兼容格式）
    messages = [{
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{base64_data}"},
            },
            {
                "type": "text",
                "text": description_prompt,
            },
        ],
    }]

    # 5. 调用 VLM 生成描述
    description = await vlm_client.generate_text(
        prompt=messages,
        max_tokens=1024,
        temperature=0.3,
    )

    if not description or not description.strip():
        raise ValueError(f"VLM 返回空描述，模型: {vlm_model}")

    # 6. 截断到 2000 字符
    description = description.strip()[:2000]

    return description


async def _generate_questions_for_chunks_static(
    chunks: List[str],
    document_title: str,
    kb_config: Dict[str, Any],
    embedding_config: Dict[str, Any],
    user_id: Optional[int] = None,
    session: Optional[AsyncSession] = None,
) -> tuple:
    """
    为所有分块生成假设问题，并生成问题向量

    Returns:
        (questions_list, question_embeddings_list)
        questions_list: List[List[str]] — 每个分块对应的问题文本列表
        question_embeddings_list: List[List[List[float]]] — 每个分块对应的问题向量列表
    """
    from src.features.knowledge_space.services.question_generation_service import (
        QuestionGenerationService,
    )
    from src.features.knowledge_space.schemas.knowledge_base_schema import (
        QuestionGenerationConfig,
    )

    _logger = get_logger(__name__)

    qg_config_dict = kb_config.get("question_generation", {})
    qg_config = QuestionGenerationConfig(**qg_config_dict) if qg_config_dict else QuestionGenerationConfig()

    if not qg_config.enabled:
        _logger.info("假设问题生成未启用，跳过")
        return [], []

    qg_service = QuestionGenerationService(session=session, config=qg_config)

    # generate_questions_batch 接受 List[Tuple[str, Optional[str]]] 格式
    chunk_tuples = [(chunk, document_title) for chunk in chunks]
    batch_results = await qg_service.generate_questions_batch(
        chunks=chunk_tuples,
        user_id=user_id,
    )

    # 提取问题文本
    questions_list: List[List[str]] = []
    all_questions_flat: List[str] = []

    for chunk_questions in batch_results:
        texts = [q.question for q in chunk_questions]
        questions_list.append(texts)
        all_questions_flat.extend(texts)

    # 生成问题向量
    question_embeddings_list: List[List[List[float]]] = []
    if all_questions_flat:
        try:
            all_q_embeddings = await _generate_embeddings_static(
                all_questions_flat,
                embedding_config,
                session=session,
                user_id=user_id,
            )
            # 将扁平的向量列表按每个分块的问题数量分组
            idx = 0
            for chunk_questions in batch_results:
                count = len(chunk_questions)
                question_embeddings_list.append(all_q_embeddings[idx:idx + count])
                idx += count
        except Exception as e:
            _logger.warning("问题向量生成失败，跳过向量", error=str(e))
            question_embeddings_list = [[] for _ in batch_results]
    else:
        question_embeddings_list = [[] for _ in batch_results]

    return questions_list, question_embeddings_list
