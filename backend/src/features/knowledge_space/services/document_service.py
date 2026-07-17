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
import traceback
import tempfile
from novamind.shared.utils.time_utils import now_china
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.document_task import TaskStatus, TaskProcessMode
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.document_task_batch_repository import DocumentTaskBatchRepository
from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository
from novamind.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.repository.space_repository import SpaceRepository
from novamind.features.knowledge_space.services.permission_service import PermissionService
from novamind.features.knowledge_space.api.exceptions import (
    KnowledgeBaseNotFoundError,
    DocumentNotFoundError,
    DocumentAlreadyExistsError,
    DocumentConversionError,
    DocumentInvalidTypeError,
    DocumentSizeExceededError,
    DocumentProcessingError,
    DocumentAlreadyProcessingError,
    InvalidParameterError,
    SpaceAccessDeniedError,
    EmbeddingError,
)
from novamind.shared.storage.minio_client import MinioClient
from novamind.shared.storage.elasticsearch_client import ElasticsearchClient
from novamind.shared.knowledge.document_processing.converters.doc_converter import convert_doc_to_docx, DocConversionError
from novamind.shared.knowledge.document_processing.pipeline import DocumentProcessor
from novamind.shared.knowledge.document_processing.validation import validate_file
from novamind.shared.knowledge.media_processing.audio import upload_parsed_text_to_minio
from novamind.shared.knowledge.media_processing.vlm import (
    build_vlm_image_messages,
    generate_vlm_text_with_fallback,
)
from novamind.shared.ai_models.embedding import OpenAICompatibleEmbedding as EmbeddingClient
from novamind.features.knowledge_space.schemas.knowledge_base_schema import build_runtime_parsing_config
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.models.document_task_batch import BatchAction


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
    from novamind.shared.mq.task_tracker import is_document_cancelled
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
    SUPPORTED_FILE_TYPES = ["pdf", "doc", "docx", "txt", "md", "csv", "html", "json", "jpg", "jpeg", "png", "gif", "webp", "mp4", "mov", "avi", "mkv", "webm", "mp3", "wav", "flac", "aac", "ogg", "m4a"]

    # 图片文件类型（从 MinIO 工具收敛到唯一定义）
    from novamind.shared.storage.minio_client import IMAGE_FILE_TYPES as _IMG_TYPES
    IMAGE_FILE_TYPES = _IMG_TYPES

    # 视频文件类型
    VIDEO_FILE_TYPES = frozenset({"mp4", "mov", "avi", "mkv", "webm"})

    # 音频文件类型
    AUDIO_FILE_TYPES = frozenset({"mp3", "wav", "flac", "aac", "ogg", "m4a"})

    # 模态 → 文件类型映射（用于上传校验和管道分流）
    MODALITY_TO_FILE_TYPES = {
        "text":  frozenset({"pdf", "doc", "docx", "txt", "md", "csv", "html", "json"}),
        "image": IMAGE_FILE_TYPES,
        "video": VIDEO_FILE_TYPES,
        "audio": AUDIO_FILE_TYPES,
    }

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
        status: Optional[int] = None,
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
        filename, file_content = await self._normalize_upload_file(filename, file_content)
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

        # 5.5 根据知识库模态校验文件类型
        file_type = file_info.extension
        from novamind.features.knowledge_space.services.knowledge_base_service import get_effective_space_types
        space = await self.space_repo.get_by_id(kb.space_id)
        modalities = get_effective_space_types(kb_config=kb.get_config())

        # 计算允许的文件类型合集（任意模态组合自动生效）
        allowed_types = set()
        for m in modalities:
            if m in self.MODALITY_TO_FILE_TYPES:
                allowed_types |= self.MODALITY_TO_FILE_TYPES[m]

        if file_type not in allowed_types:
            raise DocumentInvalidTypeError(
                f"{file_type}: 该空间不支持此文件类型。空间模态: {modalities}"
            )

        # 6. 检查文件大小
        file_size = len(file_content)
        max_size = self._get_max_file_size(kb, file_type)
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
            soft_deleted.undelete(uploader_id=uploader_id, filename=filename)

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
        async with self.session.begin_nested():
            # 创建文档记录（先获取 document_id）
            document = await self.doc_repo.create({
                "space_id": kb.space_id,
                "kb_id": kb_id,
                "uploader_id": uploader_id,
                "filename": filename,
                "file_type": file_type,
                "file_size": file_size,
                "file_hash": file_hash,
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

    async def _normalize_upload_file(self, filename: str, file_content: bytes) -> tuple[str, bytes]:
        ext = self._get_file_type(filename)
        if ext != "doc":
            return filename, file_content

        target_filename = f"{Path(filename).stem}.docx"
        try:
            converted_bytes = await convert_doc_to_docx(file_content, filename)
        except DocConversionError as exc:
            raise DocumentConversionError(str(exc), file_type="doc") from exc

        self.logger.info(
            "上传文件已从 .doc 自动转换为 .docx",
            source_filename=filename,
            target_filename=target_filename,
        )
        return target_filename, converted_bytes

    @staticmethod
    async def execute_document_pipeline(
        session: AsyncSession,
        document_id: int,
        kb_id: int,
        space_id: int,
        file_content: bytes,
        filename: str,
        task: Optional["DocumentTask"] = None,
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

        # 获取或确保任务记录
        if task is None:
            from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository
            from novamind.features.knowledge_space.models.document_task import TaskStatus
            _task_repo = DocumentTaskRepository(session)
            task = await _task_repo.get_by_document_id(document_id)
            if task is None:
                task = await _task_repo.create({
                    "document_id": document_id,
                    "kb_id": kb_id,
                    "space_id": space_id,
                    "status": TaskStatus.PENDING,
                    "pipeline_config": None,
                    "queued_at": now_china(),
                })
        if task.status.value not in (1,):  # not already PROCESSING
            task.mark_processing()

        kb = await kb_repo.get_by_id(document.kb_id)
        if not kb:
            return

        # ===== 图片文档分支 =====
        file_ext = document.file_type.lower() if document.file_type else ""

        if file_ext in DocumentService.IMAGE_FILE_TYPES:
            await _process_image_document_static(
                document, file_content, session, _logger, task=task
            )
            return

        # ===== 视频文档分支（新增） =====
        if file_ext in DocumentService.VIDEO_FILE_TYPES:
            from novamind.features.knowledge_space.services.media_processing import process_video_document
            await process_video_document(document, file_content, session, _logger, task=task)
            return

        # ===== 音频文档分支（新增） =====
        if file_ext in DocumentService.AUDIO_FILE_TYPES:
            from novamind.features.knowledge_space.services.media_processing import process_audio_document
            await process_audio_document(document, file_content, session, _logger, task=task)
            return

        # ===== 文本文档分支（现有逻辑）=====
        # 获取空间配置（提前获取，语义切分和向量化都依赖）
        space = await session.get(KnowledgeSpace, document.space_id)
        embedding_model_name = space.embedding_model if space else None
        space_owner_id = space.owner_id if space else None

        # 获取 DocumentProcessor（传入空间配置的嵌入模型，确保语义切分使用正确模型）
        processor = await _get_document_processor_static(session, user_id=space_owner_id, model_name=embedding_model_name)
        kb_config = (task.pipeline_config if task and task.pipeline_config else kb.get_config() or {})
        splitting_config = kb_config.get("splitting", {})
        suffix = f".{document.file_type}"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        try:
            # 先读取原始解析全文，避免将切块结果回拼成“伪全文”再落 MinIO。

            parsing_config = build_runtime_parsing_config(kb_config.get("parsing", {}), document.file_type)
            parse_result = await processor.parse_document_result(
                tmp_path,
                parsing_config=parsing_config,
                splitting_config=splitting_config,
            )
            full_text = parse_result.full_text
            chunks = parse_result.chunks
            task.set_step("parsed", "done")

            # 解析全文持久化到 MinIO（切块之前，立刻 commit 落库）

            await upload_parsed_text_to_minio(document, full_text, _logger)
            await session.commit()

            # 再基于解析全文做切分，确保全文与 chunk 的职责分离。
            # deepdoc/default 都在 processor.parse_document() 内完成解析与分块。

            task.set_step("split", "done")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # 检查点 1：文档解析完成之后

        await _check_document_cancelled(document_id)

        # 2. 准备 ES 数据
        es_chunks = _prepare_es_chunks_static(document, chunks, parse_metadata=parse_result.metadata)

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
        task.set_step("embedded", "done")

        # 检查点 2：向量化完成之后
        await _check_document_cancelled(document_id)

        # 5. 生成假设问题（由知识库配置控制）
        # 优先使用 task.pipeline_config 快照（入队时的 KB 配置），确保处理的一致性

        kb_config = (task.pipeline_config if task and task.pipeline_config
                     else kb.get_config() or {})
        qg_config = kb_config.get("question_generation", {})
        should_generate = qg_config.get("enabled", False) if qg_config else False

        if should_generate:
            try:
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

        task.set_step("indexed", "done")
        parse_summary = _extract_parse_metadata_summary(parse_result.metadata)

        # 5. 标记任务完成
        task.mark_completed(result={
            "chunk_count": len(chunks),
            "total_tokens": sum(len(c.split()) for c in chunks),
            "parse_strategy": parsing_config.get("strategy", "default"),
            "split_strategy": splitting_config.get("strategy", "recursive"),
            "chunk_size": splitting_config.get("chunk_size", DEFAULT_CHUNK_SIZE),
            "chunk_overlap": splitting_config.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP),
            "parser_class": parse_result.metadata.get("parser_class", ""),
            "pdf_mode": parse_result.metadata.get("pdf_mode", ""),
            "layout_source": parse_result.metadata.get("layout_source", ""),
            "vision_strategy": parse_result.metadata.get("vision_strategy", ""),
            "table_region_count": parse_summary["table_region_count"],
            "figure_region_count": parse_summary["figure_region_count"],
            "reading_order_count": parse_summary["reading_order_count"],
            "indexed_at": now_china().isoformat(),
        })
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

        # 2.5 有活跃处理任务时拒绝删除
        from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository
        _task_repo = DocumentTaskRepository(self.session)
        active_task = await _task_repo.get_active_by_document_id(document_id)
        if active_task:
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

    # 各模态默认最大文件大小（MB）
    _MODALITY_MAX_SIZE_MB = {"text": 100, "image": 100, "video": 500, "audio": 200}

    def _get_max_file_size(self, kb: KnowledgeBase, file_type: str = "") -> int:
        """获取最大文件大小限制，按模态区分默认值"""
        config = kb.get_config()
        limits = config.get("limits", {})
        if limits.get("max_file_size_mb"):
            return limits["max_file_size_mb"] * 1024 * 1024
        # 按模态取默认值
        for modality, types in self.MODALITY_TO_FILE_TYPES.items():
            if file_type in types:
                return self._MODALITY_MAX_SIZE_MB.get(modality, 100) * 1024 * 1024
        return 100 * 1024 * 1024

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
        from novamind.shared.mq.task_tracker import get_job_id_for_document
        from novamind.shared.mq import get_arq_pool

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

    async def cancel_processing(self, document_id: int, *, kb_id: int, space_id: int) -> bool:
        """
        取消文档处理任务

        通过 Redis 取消标记通知正在运行的 pipeline 终止，
        同时尝试通过 arq abort 取消排队中的任务，
        并更新 Task 记录为 CANCELLED。

        Args:
            document_id: 文档 ID
            kb_id: 知识库 ID（归属校验，防跨知识库越权）
            space_id: 空间 ID（归属校验，防跨空间越权）

        Returns:
            是否成功发送取消信号

        Raises:
            DocumentNotFoundError: 文档不存在或不属于该空间/知识库
            InvalidParameterError: 文档无活跃处理任务
        """
        document = await self.doc_repo.get_by_id(document_id)
        if not document or document.kb_id != kb_id or document.space_id != space_id:
            raise DocumentNotFoundError(document_id)

        # 检查是否有活跃任务
        from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository
        _task_repo = DocumentTaskRepository(self.session)
        active_task = await _task_repo.get_active_by_document_id(document_id)
        if not active_task:
            raise InvalidParameterError("只能取消处理中的文档", field="document_id")

        from novamind.shared.mq.task_tracker import (
            get_job_id_for_document, mark_document_cancelled,
        )
        from novamind.shared.mq import get_arq_pool

        # 设置取消标记（pipeline 会在检查点检测到）
        await mark_document_cancelled(document_id)

        # 更新任务状态为 CANCELLED
        active_task.mark_cancelled()

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
        from novamind.shared.mq.task_tracker import get_active_document_count
        return await get_active_document_count()

    # ========== 拆分解析方法 ==========

    async def process_kb_documents(
        self,
        kb_id: int,
        user_id: int,
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

        documents: List[Document] = []
        if not document_ids:
            documents = await self.doc_repo.get_by_kb(kb_id)
            document_ids = [doc.id for doc in documents]
        else:
            document_ids = list(dict.fromkeys(document_ids))
            documents = await self.doc_repo.get_by_ids(document_ids)

        if not document_ids:
            return {
                "task_id": None,
                "total": 0,
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "results": [],
            }

        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb or not kb.is_active():
            raise KnowledgeBaseNotFoundError(kb_id)

        current_pipeline_config = kb.get_config() if kb else None
        existing_doc_ids = [doc.id for doc in documents]
        locked_documents = await self.doc_repo.lock_active_documents_by_ids(existing_doc_ids)
        document_map = {doc.id: doc for doc in locked_documents}
        task_repo = DocumentTaskRepository(self.session)
        active_task_map = await task_repo.get_active_by_document_ids(existing_doc_ids)
        latest_task_map = await task_repo.get_latest_by_document_ids(existing_doc_ids)

        eligible_documents: List[Document] = []
        task_payloads: List[Dict[str, Any]] = []
        task_modes: Dict[int, str] = {}

        for doc_id in document_ids:
            document = document_map.get(doc_id)
            if not document:
                results.append({
                    "document_id": doc_id,
                    "status": "failed",
                    "message": str(DocumentNotFoundError(doc_id)),
                })
                continue

            if document.kb_id != kb_id:
                results.append({
                    "document_id": doc_id,
                    "status": "failed",
                    "message": "文档不属于该知识库",
                })
                continue

            if doc_id in active_task_map:
                results.append({
                    "document_id": doc_id,
                    "status": "skipped",
                    "message": "文档正在处理中，跳过",
                })
                continue

            latest_task = latest_task_map.get(doc_id)
            process_mode = TaskProcessMode.REPROCESS if latest_task and latest_task.status == TaskStatus.COMPLETED else TaskProcessMode.PROCESS

            eligible_documents.append(document)
            task_modes[doc_id] = "reprocess" if process_mode == TaskProcessMode.REPROCESS else "process"
            task_payloads.append({
                "document_id": doc_id,
                "kb_id": document.kb_id,
                "space_id": document.space_id,
                "status": TaskStatus.PENDING,
                "process_mode": process_mode,
                "pipeline_config": current_pipeline_config,
                "retry_count": 0,
                "queued_at": now_china(),
            })

        if not task_payloads:
            return {
                "task_id": None,
                "total": len(results),
                "success": 0,
                "failed": sum(1 for r in results if r["status"] == "failed"),
                "skipped": sum(1 for r in results if r["status"] == "skipped"),
                "results": results,
            }

        batch_repo = DocumentTaskBatchRepository(self.session)
        batch = await batch_repo.create({
            "space_id": eligible_documents[0].space_id,
            "kb_id": kb_id,
            "creator_id": user_id,
            "action": BatchAction.PROCESS,
            "pipeline_config": current_pipeline_config,
            "total_count": len(task_payloads),
            "note": f"批量处理 {len(task_payloads)} 个文档",
        })
        for payload in task_payloads:
            payload["batch_id"] = batch.id

        created_tasks = await task_repo.create_many(task_payloads)
        await self.session.commit()

        try:
            enqueued_jobs = await self._enqueue_precreated_tasks(created_tasks)
        except Exception as e:
            await self._cancel_batch_enqueue(batch.id, [task.id for task in created_tasks], str(e))
            for document in eligible_documents:
                results.append({
                    "document_id": document.id,
                    "task_id": batch.id,
                    "status": "failed",
                    "message": f"批量入队失败: {e}",
                })
            return {
                "task_id": None,
                "total": len(results),
                "success": 0,
                "failed": sum(1 for r in results if r["status"] == "failed"),
                "skipped": sum(1 for r in results if r["status"] == "skipped"),
                "results": results,
            }

        task_by_document_id = {task.document_id: task for task in created_tasks}
        for document in eligible_documents:
            task = task_by_document_id[document.id]
            results.append({
                "document_id": document.id,
                "task_id": batch.id,
                "task_item_id": task.id,
                "job_id": enqueued_jobs.get(task.id),
                "status": "processing",
                "message": "已触发重新解析" if task_modes[document.id] == "reprocess" else "已触发处理",
            })

        return {
            "task_id": batch.id,
            "total": len(results),
            "success": sum(1 for r in results if r["status"] == "processing"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "skipped": sum(1 for r in results if r["status"] == "skipped"),
            "results": results,
        }

    async def reprocess_document(
        self,
        document_id: int,
        *,
        batch_id: Optional[int] = None,
        batch_creator_id: Optional[int] = None,
        batch_note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """重新解析文档。"""
        document = await self._validate_document_not_processing(document_id)

        task_info = await self._enqueue_document_processing(
            document,
            "重新解析",
            batch_id=batch_id,
            batch_creator_id=batch_creator_id,
            batch_action=BatchAction.REPROCESS,
            process_mode=TaskProcessMode.REPROCESS,
            batch_note=batch_note,
        )
        return {"document": document, **task_info}

    async def retry_document(
        self,
        document_id: int,
        *,
        kb_id: int,
        space_id: int,
        batch_id: Optional[int] = None,
        batch_creator_id: Optional[int] = None,
        batch_note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """重试文档处理，支持 FAILED 和 COMPLETED 状态。"""
        document = await self._validate_document_not_processing(document_id)
        if document.kb_id != kb_id or document.space_id != space_id:
            raise DocumentNotFoundError(document_id)

        from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository
        _task_repo = DocumentTaskRepository(self.session)
        latest_task = await _task_repo.get_by_document_id(document_id)
        if not latest_task or latest_task.status not in (TaskStatus.FAILED, TaskStatus.COMPLETED):
            raise InvalidParameterError(
                "只能重试失败或已完成的文档",
                field="document_id",
            )

        task_info = await self._enqueue_document_processing(
            document,
            "重试",
            batch_id=batch_id,
            batch_creator_id=batch_creator_id,
            batch_action=BatchAction.RETRY,
            process_mode=TaskProcessMode.RETRY,
            batch_note=batch_note,
            retry_count=0,
            pipeline_config_override=latest_task.pipeline_config,
        )

        self.logger.info(
            "文档重试已入队",
            document_id=document_id,
            previous_task_id=latest_task.id,
        )
        return {"document": document, **task_info}

    # ---------- 文档处理共享辅助方法 ----------

    async def _validate_document_not_processing(self, document_id: int) -> Document:
        """获取文档并验证无活跃处理任务"""
        document = await self.doc_repo.get_by_id(document_id)
        if not document:
            raise DocumentNotFoundError(document_id)
        from novamind.features.knowledge_space.repository.document_task_repository import DocumentTaskRepository
        _task_repo = DocumentTaskRepository(self.session)
        active_task = await _task_repo.get_active_by_document_id(document_id)
        if active_task:
            raise DocumentAlreadyProcessingError(document_id)
        return document

    async def _enqueue_document_processing(
        self,
        document: Document,
        log_label: str = "处理",
        *,
        batch_id: Optional[int] = None,
        batch_creator_id: Optional[int] = None,
        batch_action: BatchAction = BatchAction.PROCESS,
        process_mode: TaskProcessMode = TaskProcessMode.PROCESS,
        batch_note: Optional[str] = None,
        retry_count: int = 0,
        pipeline_config_override: Optional[dict] = None,
    ):
        """创建任务记录并入队文档处理。"""
        from novamind.shared.mq.task_tracker import is_document_actively_processing

        if await is_document_actively_processing(document.id):
            raise DocumentAlreadyProcessingError(document.id)

        kb = await self.kb_repo.get_by_id(document.kb_id)
        pipeline_config = pipeline_config_override if pipeline_config_override is not None else (kb.get_config() if kb else None)

        from novamind.shared.mq import enqueue_process_document
        batch_data = None
        if batch_id is None and batch_creator_id is not None:
            batch_data = {
                "space_id": document.space_id,
                "kb_id": document.kb_id,
                "creator_id": batch_creator_id,
                "action": batch_action,
                "pipeline_config": pipeline_config,
                "total_count": 1,
                "note": batch_note,
            }
        return await enqueue_process_document(
            document_id=document.id,
            kb_id=document.kb_id,
            space_id=document.space_id,
            batch_id=batch_id,
            process_mode=process_mode,
            pipeline_config=pipeline_config,
            retry_count=retry_count,
            session=self.session,
            batch_data=batch_data,
        )

    async def _enqueue_precreated_tasks(self, tasks: List["DocumentTask"]) -> Dict[int, str]:
        from arq.jobs import Job
        from novamind.shared.mq import get_arq_pool
        from novamind.shared.mq.task_tracker import bind_job_to_document, unbind_job

        if not tasks:
            return {}

        pool = await get_arq_pool()
        enqueued: List[tuple[int, int, str]] = []
        try:
            for task in tasks:
                job_id = f"doc-task-{task.id}"
                job = await pool.enqueue_job(
                    "process_document_task",
                    document_id=task.document_id,
                    kb_id=task.kb_id,
                    space_id=task.space_id,
                    _job_id=job_id,
                )
                if job is None:
                    raise RuntimeError(f"批量任务入队失败: task_id={task.id}")
                task.job_id = job.job_id
                enqueued.append((task.id, task.document_id, job.job_id))

            await self.session.commit()

            for _, document_id, job_id in enqueued:
                await bind_job_to_document(document_id, job_id)

            return {task_id: job_id for task_id, _, job_id in enqueued}
        except Exception:
            await self.session.rollback()
            for _, document_id, job_id in enqueued:
                try:
                    job = Job(job_id, pool, _deserializer=pool.job_deserializer)
                    await job.abort(timeout=0)
                except Exception:
                    self.logger.warning("批量入队回滚时取消 job 失败", document_id=document_id, job_id=job_id)
                try:
                    await unbind_job(document_id)
                except Exception:
                    self.logger.warning("批量入队回滚时清理任务映射失败", document_id=document_id, job_id=job_id)
            raise

    async def _cancel_batch_enqueue(self, batch_id: int, task_ids: List[int], error_message: str) -> None:
        from sqlalchemy import update
        from novamind.core.database.database import get_db_session
        from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
        from novamind.features.knowledge_space.models.document_task_batch import DocumentTaskBatch, BatchStatus

        async with get_db_session() as session:
            if task_ids:
                await session.execute(
                    update(DocumentTask)
                    .where(DocumentTask.id.in_(task_ids))
                    .values(
                        status=TaskStatus.CANCELLED,
                        error_message=f"[批量入队失败] {error_message[:300]}",
                        completed_at=now_china(),
                    )
                )
            await session.execute(
                update(DocumentTaskBatch)
                .where(DocumentTaskBatch.id == batch_id)
                .values(
                    status=BatchStatus.FAILED,
                    error_message=f"[批量入队失败] {error_message[:300]}",
                    completed_at=now_china(),
                )
            )
            await session.commit()


# ========== 模块级静态辅助函数 ==========


async def _process_image_document_static(
    document: Document,
    file_content: bytes,
    session,
    _logger,
    task=None,
):
    """处理图片类型文档：生成多模态嵌入向量并索引到 ES

    支持两种模式：
    - VLM 关闭：仅生成 image_embedding，content 不写入，仅支持以图搜图
    - VLM 开启：额外调用视觉模型生成描述文本 + text embedding，支持 BM25 + 文本向量 + 以图搜图
    """
    from novamind.shared.ai_models.embedding import BaseMultimodalEmbedding

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
        # 优先使用 task.pipeline_config 快照
        kb_config = (task.pipeline_config if task and task.pipeline_config
                     else kb.get_config() or {})
        parsing_config = build_runtime_parsing_config(kb_config.get("parsing", {}), document.file_type)
        vlm_enabled = parsing_config.get("vlm_description_enabled", False)

    # 检查点 0：配置读取后
    await _check_document_cancelled(document.id)

    # 2. 获取多模态嵌入客户端
    from novamind.features.user.services.model_config_service import ModelConfigService
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
            vlm_model_name = parsing_config.get("vlm_model")
            description_text = await _generate_image_description(
                file_content=file_content,
                document=document,
                mcs=mcs,
                _logger=_logger,
                vlm_model_name=vlm_model_name,
            )

            if description_text:
                # 图片描述全文持久化到 MinIO（立刻 commit 落库）
                await upload_parsed_text_to_minio(document, description_text, _logger)
                await session.commit()

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

    # 7. 标记任务完成
    result = {
        "chunk_count": 1,
        "indexed_at": now_china().isoformat(),
        "chunk_type": "image",
    }
    if vlm_enabled and description_text:
        result["vlm_description"] = True
        result["description_length"] = len(description_text)
    if task:
        task.mark_completed(result=result)
    await session.commit()

    _logger.info(
        "图片文档处理完成",
        document_id=document.id,
        model=model_name,
        vector_dim=len(image_vector),
        vlm_enabled=vlm_enabled,
        has_description=bool(description_text),
    )


def _prepare_es_chunks_static(
    document: Document,
    chunks: List[str],
    parse_metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    将文本分块列表转换为 ES 索引格式的字典列表

    Args:
        document: 文档对象
        chunks: 文本分块列表
        parse_metadata: 解析阶段产出的附加 metadata

    Returns:
        ES 索引格式的分块字典列表
    """
    es_chunks = []
    storage_info = document.storage or {}
    parse_metadata = dict(parse_metadata or {})
    parse_summary = _extract_parse_metadata_summary(parse_metadata)
    chunk_structure = list(parse_metadata.get("chunk_structure") or [])
    for i, chunk_text in enumerate(chunks):
        structure = chunk_structure[i] if i < len(chunk_structure) else {}
        chunk_data = {
            "space_id": document.space_id,
            "kb_id": document.kb_id,
            "document_id": document.id,
            "chunk_id": f"{document.id}_{i}",
            "chunk_index": i,
            "content": chunk_text,
            "chunk_type": "text",
            "media_url": storage_info.get("minio_object_name", ""),
            "file_info": {
                "filename": document.filename,
                "file_type": document.file_type,
            },
            "metadata": {
                "content_hash": document.file_hash,
                "parser": parse_metadata.get("parser", ""),
                "file_type": parse_metadata.get("file_type", document.file_type),
                **parse_summary,
                "chunk_entry_kinds": list(structure.get("entry_kinds") or []),
                "chunk_entry_source_ids": list(structure.get("entry_source_ids") or []),
                "chunk_pages": list(structure.get("pages") or []),
                "chunk_entry_count": int(structure.get("entry_count") or 0),
            },
            "questions": [],
            "question_embeddings": [],
            "created_at": now_china().isoformat(),
        }
        es_chunks.append(chunk_data)
    return es_chunks


def _extract_parse_metadata_summary(parse_metadata: Dict[str, Any]) -> Dict[str, Any]:
    table_regions = list(parse_metadata.get("table_regions") or [])
    figure_regions = list(parse_metadata.get("figure_regions") or [])
    reading_order = list(parse_metadata.get("reading_order") or [])
    return {
        "parser_class": parse_metadata.get("parser_class", ""),
        "pdf_mode": parse_metadata.get("pdf_mode", ""),
        "layout_source": parse_metadata.get("layout_source", ""),
        "vision_strategy": parse_metadata.get("vision_strategy", ""),
        "table_region_count": len(table_regions),
        "figure_region_count": len(figure_regions),
        "reading_order_count": len(reading_order),
    }


async def _get_es_client_static() -> ElasticsearchClient:
    """获取 ES 客户端（静态方法用）"""
    from novamind.shared.clients import ClientFactory
    return await ClientFactory.get_elasticsearch_client()


async def _get_document_processor_static(session: AsyncSession, user_id: Optional[int] = None, model_name: Optional[str] = None) -> DocumentProcessor:
    """获取文档处理器（静态方法用）"""
    from novamind.features.user.services.model_config_service import ModelConfigService

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
        try:
            embeddings = await embedding_client.generate_embeddings_batch(batch)
        except Exception as e:
            _log = get_logger(__name__)
            _log.error(
                "Embedding 批量生成失败",
                model_name=model_name,
                batch_start=i,
                batch_size=len(batch),
                error=str(e),
                traceback=traceback.format_exc(),
            )
            raise EmbeddingError(
                f"Embedding 生成失败: model={model_name or 'unknown'}, batch_start={i}, error={e}"
            ) from e
        all_embeddings.extend(embeddings)
    return all_embeddings


async def _get_embedding_client_static(
    session: AsyncSession,
    user_id: Optional[int] = None,
    model_name: Optional[str] = None,
) -> EmbeddingClient:
    """获取 Embedding 客户端（静态方法用）"""
    from novamind.features.user.services.model_config_service import ModelConfigService

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
        _log.warning("单条文本嵌入生成失败", error=str(e), traceback=traceback.format_exc())
        return None


async def _generate_image_description(
    file_content: bytes,
    document: Document,
    mcs,  # ModelConfigService
    _logger,
    vlm_model_name: Optional[str] = None,
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
    from novamind.shared.prompts.templates import PromptManager, PromptTemplate

    # 1. 获取 VLM 客户端
    vlm_model = vlm_model_name or await mcs.get_user_default_model_name(document.uploader_id, "vlm")
    if not vlm_model:
        raise ValueError("未配置 VLM 模型，请在模型配置中添加视觉模型")

    vlm_client = await mcs.get_vlm_client_by_model(document.uploader_id, vlm_model)

    file_ext = (document.file_type or "png").lower()
    mime_type = f"image/{file_ext}" if file_ext != "jpg" else "image/jpeg"

    # 3. 获取描述 Prompt
    description_prompt = PromptManager.get_template(PromptTemplate.IMAGE_DESCRIPTION.value)

    # 4. 构建多模态消息（OpenAI 兼容格式）
    messages = build_vlm_image_messages(
        file_bytes=file_content,
        mime_type=mime_type,
        text_prompt=description_prompt,
    )

    # 5. 调用 VLM 生成描述
    description = await generate_vlm_text_with_fallback(
        vlm_client=vlm_client,
        messages=messages,
        max_tokens=1024,
        temperature=0.3,
        logger=_logger,
        vlm_model=vlm_model,
        log_context={
            "document_id": document.id,
            "file_type": document.file_type,
        },
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
    from novamind.features.knowledge_space.services.question_generation_service import (
        QuestionGenerationService,
    )
    from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
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
