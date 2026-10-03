"""文档上传服务：上传校验与 MinIO 落库，不触发解析（.doc 自动转 .docx）。

_compute_sha256 为 CPU 密集操作，须由调用方放线程池执行。
"""

import asyncio
import hashlib
import io
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.document.converters.doc_converter import (
    DocConversionError,
    convert_doc_to_docx,
)
from novamind.features.knowledge_space.exceptions import (
    DocumentAlreadyExistsError,
    DocumentConversionError,
    DocumentInvalidTypeError,
    DocumentSizeExceededError,
    InvalidParameterError,
    KnowledgeBaseNotFoundError,
    SpaceAccessDeniedError,
)
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.schemas.document_schema import UploadedDocumentResult
from novamind.features.knowledge_space.services.permission_service import SpaceAccessChecker
from novamind.shared.document.validation import validate_file
from novamind.shared.storage.minio_client import MinioClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _compute_sha256(content: bytes) -> str:
    """计算 SHA256 哈希（CPU 密集操作，用于在线程池中执行）"""
    return hashlib.sha256(content).hexdigest()


class DocumentUploadService:
    """文档上传服务：校验 + MinIO 落库（不触发解析）。"""

    # 文件类型常量收敛到 document_file_types（upload 校验引用）
    from novamind.features.knowledge_space.services.document_file_types import (
        MODALITY_TO_FILE_TYPES,
        SUPPORTED_FILE_TYPES,
    )

    # 各模态默认最大文件大小（MB）。video 2000：大视频经流式管道（上传流式哈希
    # + MinIO multipart + worker 落盘抽帧），内存峰值与文件大小解耦；KB 级
    # limits.max_file_size_mb 可覆盖任一模态默认值。
    _MODALITY_MAX_SIZE_MB = {"text": 100, "image": 100, "video": 2000, "audio": 200}

    def __init__(self, session: AsyncSession, minio_client: MinioClient):
        """构造注入会话与 MinIO 客户端，内置仓储与权限检查器。"""
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.kb_repo = KnowledgeBaseRepository(session)
        self.minio_client = minio_client
        self.logger = get_logger(__name__)
        self.member_repo = MemberRepository(session)
        self.permission_service = SpaceAccessChecker()

    async def upload_document(
        self,
        kb_id: int,
        uploader_id: int,
        file_content: bytes,
        filename: str,
        metadata: dict[str, Any] | None = None,
    ) -> UploadedDocumentResult:
        """上传文档（仅存 MinIO，不触发解析）。

        Args:
            kb_id: 知识库 ID
            uploader_id: 上传者 ID
            file_content: 文件内容
            filename: 文件名
            metadata: 文档元数据

        Returns:
            上传结果 DTO（document_id/filename/file_size）。不返回 ORM 实例，
            避免批量上传中后续 rollback 导致实例 expire、路由层访问属性时
            触发同步懒加载（MissingGreenlet）。

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
            raise SpaceAccessDeniedError(
                kb.space_id, uploader_id, "需要编辑者或更高权限才能上传文档"
            )

        # 4. 获取允许的文件类型
        filename, file_content = await self._normalize_upload_file(filename, file_content)
        allowed_types = self._get_allowed_file_types(kb)

        # 预判文件模态（决定 validator 大小上限覆盖：video 500 / audio 200 MB，
        # 修复模态上限被全局 100MB 闸提前拦死的死配置问题——审计 P2）
        preview_ext = self._get_file_type(filename)
        modality_limit = self._MODALITY_MAX_SIZE_MB.get("text", 100)
        for _mod, _types in self.MODALITY_TO_FILE_TYPES.items():
            if preview_ext in _types:
                modality_limit = self._MODALITY_MAX_SIZE_MB.get(_mod, 100)
                break

        # 5. 验证文件（使用 python-magic 检测真实 MIME 类型），按模态传大小上限。
        #    校验入线程池：python-magic + zip 容器解析是 CPU/IO 同步操作，
        #    且 upload_document 位于 API 请求路径（嵌入式 worker 与 API 共享
        #    事件循环，同步阻塞会卡住全部并发请求——评审 P2-2）。
        file_info = await asyncio.to_thread(
            validate_file,
            content=file_content,
            filename=filename,
            allowed_extensions=allowed_types,
            max_file_size=modality_limit * 1024 * 1024,
        )

        if not file_info.is_valid:
            self.logger.warning(
                "文件验证失败",
                filename=filename,
                extension=file_info.extension,
                detected_mime=file_info.detected_mime,
                message=file_info.validation_message,
            )
            raise DocumentInvalidTypeError(f"{file_info.extension}: {file_info.validation_message}")

        file_type = await self._check_kb_modality(kb, file_info.extension)

        # 6. 检查文件大小
        file_size = len(file_content)
        max_size = self._get_max_file_size(kb, file_type)
        if file_size > max_size:
            raise DocumentSizeExceededError(file_size, max_size)

        # 7. 计算文件哈希（CPU 密集操作放入线程池）
        file_hash = await asyncio.to_thread(_compute_sha256, file_content)

        return await self._dedup_and_persist(
            kb=kb,
            kb_id=kb_id,
            uploader_id=uploader_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            file_hash=file_hash,
            upload_bytes=file_content,
        )

    async def upload_document_streamed(
        self,
        kb_id: int,
        uploader_id: int,
        file,
        *,
        read_limit: int,
    ) -> UploadedDocumentResult:
        """大文件流式上传（仅存 MinIO，不触发解析）——文件全程不进内存。

        与 ``upload_document`` 共享校验/查重/持久化语义（模态校验、SAVEPOINT、
        IntegrityError 兜底、孤儿补偿、hash 缓存同步），差异仅在数据形态：
        UploadFile 的 SpooledTemporaryFile 经 ingest_upload_stream 流式哈希+计数，
        校验魔数只读头部少量字节，MinIO 上传走 multipart 流式。

        Args:
            kb_id: 知识库 ID。
            uploader_id: 上传者 ID。
            file: FastAPI UploadFile（file 属性为 SpooledTemporaryFile）。
            read_limit: 读取字节硬顶（全局流式读上限，防 Content-Length
                撒谎/chunked encoding 绕过模态闸）。

        Returns:
            上传结果 DTO（document_id/filename/file_size）。

        Raises:
            KnowledgeBaseNotFoundError: 知识库不存在。
            DocumentAlreadyExistsError: 同哈希文档已存在。
            DocumentInvalidTypeError: 类型不支持/魔数不匹配/空间模态不符。
            DocumentSizeExceededError: 流式计数超过 read_limit 或模态上限。
            InvalidParameterError: 文件名非法。
        """
        # 1-3. 参数/KB/权限：与整包路径共用前置（异常语义一致）
        if not file.filename or not file.filename.strip():
            raise InvalidParameterError("文件名不能为空", field="filename")

        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb:
            raise KnowledgeBaseNotFoundError(kb_id)

        member = await self.member_repo.get_by_space_and_user(kb.space_id, uploader_id)
        if not member or not member.is_active():
            raise SpaceAccessDeniedError(kb.space_id, uploader_id, "无权在此知识库上传文档")
        if not self.permission_service.can_upload_document(member):
            raise SpaceAccessDeniedError(
                kb.space_id, uploader_id, "需要编辑者或更高权限才能上传文档"
            )

        # 4. 文件名校验（_get_file_type 含长度/字符/路径遍历/白名单检查）
        filename = file.filename
        ext = self._get_file_type(filename)
        allowed_types = self._get_allowed_file_types(kb)
        file_type = await self._check_kb_modality(kb, ext)

        # 5. 流式哈希 + 硬计数（read_limit 兜底模态闸之前的全局上限）
        file_hash, file_size = await self.ingest_upload_stream(file, max_size=read_limit)

        # 6. 模态大小上限（权威校验，与整包路径同源）
        max_size = self._get_max_file_size(kb, file_type)
        if file_size > max_size:
            raise DocumentSizeExceededError(file_size, max_size)

        # 7. 魔数校验：validate_file 只消费头部（libmagic 前 2KB + zip 容器
        #    Content_Types 读取），此处读头部回卷，避免整包进内存。
        def _read_head(stream: io.BufferedIOBase, size: int) -> bytes:
            stream.seek(0)
            head = stream.read(size)
            stream.seek(0)
            return head

        head_size = min(file_size, self._MAGIC_HEAD_BYTES)
        head = await asyncio.to_thread(_read_head, file.file, head_size)
        file_info = await asyncio.to_thread(
            validate_file,
            content=head,
            filename=filename,
            allowed_extensions=allowed_types,
            max_file_size=max_size,
        )
        if not file_info.is_valid:
            self.logger.warning(
                "文件验证失败",
                filename=filename,
                extension=file_info.extension,
                detected_mime=file_info.detected_mime,
                message=file_info.validation_message,
            )
            raise DocumentInvalidTypeError(f"{file_info.extension}: {file_info.validation_message}")

        # 8-9. 查重 + 持久化 + MinIO 流式上传（与整包路径同一尾段）
        return await self._dedup_and_persist(
            kb=kb,
            kb_id=kb_id,
            uploader_id=uploader_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            file_hash=file_hash,
            upload_bytes=None,
            upload_stream=file.file,
        )

    # 魔数校验头部读取量：libmagic 消费前 2KB，zip 容器（docx 等）的
    # [Content_Types].xml 位于首个局部文件头之后，8KB 覆盖其在常规文件中的位置；
    # 超出此窗口仍读不到签名表命中的类型时 validate_file 按既有两级探测判拒。
    _MAGIC_HEAD_BYTES = 8 * 1024

    async def _check_kb_modality(self, kb: KnowledgeBase, extension: str) -> str:
        """按知识库有效模态合集校验扩展名，通过则返回该扩展名。"""
        from novamind.features.knowledge_space.services.knowledge_base_service import (
            get_effective_space_types,
        )

        modalities = get_effective_space_types(kb_config=kb.get_config())

        # 计算允许的文件类型合集（任意模态组合自动生效）
        allowed_types = set()
        for m in modalities:
            if m in self.MODALITY_TO_FILE_TYPES:
                allowed_types |= self.MODALITY_TO_FILE_TYPES[m]

        if extension not in allowed_types:
            raise DocumentInvalidTypeError(
                f"{extension}: 该空间不支持此文件类型。空间模态: {modalities}"
            )
        return extension

    async def _dedup_and_persist(
        self,
        *,
        kb: KnowledgeBase,
        kb_id: int,
        uploader_id: int,
        filename: str,
        file_type: str,
        file_size: int,
        file_hash: str,
        upload_bytes: bytes | None,
        upload_stream: io.BufferedIOBase | None = None,
    ) -> UploadedDocumentResult:
        """查重后持久化文档（软删复活或新建），再按入参形态上传 MinIO。

        ``upload_bytes``（整包路径）与 ``upload_stream``（大文件流式路径）二选一：
        前者走 upload_document（内存 buffer），后者走 upload_document_streamed
        （SpooledTemporaryFile 流式，方法内部 seek(0) 回卷）。查重（活跃命中、
        软删复活）与 SAVEPOINT/IntegrityError 兜底/孤儿对象补偿两条路径语义
        与历史 upload_document 完全一致。

        Raises:
            DocumentAlreadyExistsError: 同哈希活跃文档已存在，或唯一约束兜底命中。
        """
        if (upload_bytes is None) == (upload_stream is None):
            raise ValueError("upload_bytes 与 upload_stream 必须二选一")

        # 8. 检查重复（去重范围：同知识库 + 同上传者的活跃文档）
        existing = await self.doc_repo.get_by_hash(kb_id, uploader_id, file_hash)
        if existing:
            raise DocumentAlreadyExistsError(
                filename,
                existing_document_id=existing.id,
                existing_filename=existing.filename,
            )

        # 8.1 检查是否有同 hash 的已软删除文档（限同上传者，可复用记录）
        soft_deleted = await self.doc_repo.get_deleted_by_hash(kb_id, uploader_id, file_hash)
        if soft_deleted:
            # 复活已软删除记录 + 重新上传 MinIO 用 SAVEPOINT 保证原子性：
            # 若 MinIO 上传失败，undelete 的 ORM 改动随 SAVEPOINT 自动回滚，
            # 不会留下"已复活但无对象"的脏记录（与下方新建分支同构）。
            async with self.session.begin_nested():
                soft_deleted.undelete(uploader_id=uploader_id, filename=filename)

                # 重新上传 MinIO（软删除时文件已被清理）
                minio_result = await self._upload_to_minio(
                    kb=kb,
                    kb_id=kb_id,
                    document_id=soft_deleted.id,
                    filename=filename,
                    file_hash=file_hash,
                    file_size=file_size,
                    upload_bytes=upload_bytes,
                    upload_stream=upload_stream,
                )
                soft_deleted.set_minio_info(
                    bucket=minio_result["bucket"],
                    object_name=minio_result["object_name"],
                    etag=minio_result.get("etag"),
                )

            await self.session.commit()

            # 更新 hash 缓存（该 hash 现在又有活跃文档了）
            await self.doc_repo.cache_document_hash(kb_id, uploader_id, file_hash, exists=True)

            self.logger.info(
                "复活已删除文档",
                document_id=soft_deleted.id,
                kb_id=kb_id,
                uploader_id=uploader_id,
            )
            # 在 session 仍活跃时把标量读入 DTO，避免后续 rollback expire 实例。
            return UploadedDocumentResult(
                document_id=soft_deleted.id,
                filename=soft_deleted.filename,
                file_size=soft_deleted.file_size,
            )

        # 9. 创建文档记录 + 上传 MinIO（使用 SAVEPOINT 保证原子性）
        # 注意：doc_repo.create 先 flush 出真实 document_id 再上传 MinIO，因此
        # 唯一约束冲突（uq_kb_uploader_file_hash）发生在 flush 阶段、MinIO 上传之前，
        # 不会产生孤儿对象。
        try:
            async with self.session.begin_nested():
                # 创建文档记录（先获取 document_id）
                document = await self.doc_repo.create(
                    {
                        "space_id": kb.space_id,
                        "kb_id": kb_id,
                        "uploader_id": uploader_id,
                        "filename": filename,
                        "file_type": file_type,
                        "file_size": file_size,
                        "file_hash": file_hash,
                    }
                )

                # 使用真实 document_id 上传到 MinIO
                minio_result = await self._upload_to_minio(
                    kb=kb,
                    kb_id=kb_id,
                    document_id=document.id,
                    filename=filename,
                    file_hash=file_hash,
                    file_size=file_size,
                    upload_bytes=upload_bytes,
                    upload_stream=upload_stream,
                )

                # 更新文档记录中的存储信息
                document.set_minio_info(
                    bucket=minio_result["bucket"],
                    object_name=minio_result["object_name"],
                    etag=minio_result.get("etag"),
                )

            await self.session.commit()
        except IntegrityError:
            # uq_kb_uploader_file_hash 冲突：同知识库同上传者已存在相同哈希的文档。
            # 正常情况下步骤 8 的去重检查会先命中并抛出 DocumentAlreadyExistsError，
            # 这里只兜底两类漏网场景——(a) 哈希缓存残留 exists=False 导致 get_by_hash
            # 跳过 DB 查询，(b) 并发上传竞争。SAVEPOINT 已自动回滚，再抛业务异常避免 500。
            await self.session.rollback()
            # rollback 后重新查询冲突文档，报错时点名已有文件；查不到（竞态窗口）
            # 则退化为仅报本次文件名。
            conflicting = await self.doc_repo.get_by_hash(
                kb_id, uploader_id, file_hash, use_cache=False
            )
            raise DocumentAlreadyExistsError(
                filename,
                existing_document_id=conflicting.id if conflicting else None,
                existing_filename=conflicting.filename if conflicting else None,
            )
        except Exception:
            # commit 失败（连接断开等）：DB 行已回滚，但 MinIO 对象已上传——
            # 不补偿会成为无 DB 引用的孤儿对象（审计 P2）。best-effort 删除。
            storage = getattr(document, "storage", None) or {}
            bucket = storage.get("minio_bucket")
            object_name = storage.get("minio_object_name")
            if bucket and object_name:
                try:
                    from novamind.shared.storage.minio_client import MinioClient

                    deleted = await MinioClient.delete_document(
                        self.minio_client, bucket_name=bucket, object_name=object_name,
                    )
                    self.logger.warning(
                        "上传 commit 失败，已补偿删除 MinIO 孤儿对象",
                        bucket=bucket, object_name=object_name, deleted=deleted,
                    )
                except Exception as cleanup_err:
                    self.logger.error(
                        "上传 commit 失败且 MinIO 孤儿补偿删除失败（对象残留）",
                        bucket=bucket, object_name=object_name, error=str(cleanup_err),
                    )
            raise

        # 创建成功后同步哈希缓存为 exists=True。步骤 8 的 get_by_hash 在未命中时会
        # 缓存 exists=False，若创建后不更正，后续同哈希上传会因缓存命中而绕过去重
        # 检查、直接撞上 uq_kb_uploader_file_hash 唯一约束（正是批量重传时的
        # IntegrityError）。
        await self.doc_repo.cache_document_hash(kb_id, uploader_id, file_hash, exists=True)

        self.logger.info(
            "文档上传成功，等待拆分解析",
            document_id=document.id,
            kb_id=kb_id,
            filename=filename,
            uploader_id=uploader_id,
        )

        # 在 session 仍活跃时把标量读入 DTO，避免后续 rollback expire 实例。
        return UploadedDocumentResult(
            document_id=document.id,
            filename=document.filename,
            file_size=document.file_size,
        )

    async def _upload_to_minio(
        self,
        *,
        kb: KnowledgeBase,
        kb_id: int,
        document_id: int,
        filename: str,
        file_hash: str,
        file_size: int,
        upload_bytes: bytes | None,
        upload_stream: io.BufferedIOBase | None,
    ) -> dict[str, Any]:
        """按入参形态上传 MinIO：整包 bytes 走缓冲上传，流走 multipart 流式。

        流式分支委托 upload_document_streamed（内部 seek(0) 回卷 + put_object
        自动 multipart），要求 file_size 与流长度严格一致——由 ingest_upload_stream
        的计数保证。两条路径的存储命名/返回结构完全一致。
        """
        if upload_bytes is not None:
            return await self.minio_client.upload_document(
                space_id=kb.space_id,
                kb_id=kb_id,
                document_id=document_id,
                file_data=upload_bytes,
                filename=filename,
                file_hash=file_hash,
            )
        assert upload_stream is not None  # 互斥性由 _dedup_and_persist 前置校验
        return await self.minio_client.upload_document_streamed(
            space_id=kb.space_id,
            kb_id=kb_id,
            document_id=document_id,
            file_stream=upload_stream,
            file_size=file_size,
            filename=filename,
            file_hash=file_hash,
        )

    async def upload_documents(
        self,
        kb_id: int,
        uploader_id: int,
        files: list[tuple],
    ) -> dict:
        """批量上传文档（仅存 MinIO，不触发解析）。

        单个文件失败不影响其他文件。

        Args:
            kb_id: 知识库 ID
            uploader_id: 上传者 ID
            files: [(filename, file_content), ...] 文件列表

        Returns:
            {"success": [UploadedDocumentResult, ...], "failed": [{"filename": str, "error": str}, ...]}
        """
        success: list[UploadedDocumentResult] = []
        failed: list[dict] = []

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
    async def read_upload_file(file, *, max_size: int = 100 * 1024 * 1024) -> bytes:
        """分块读取单个上传文件内容，带大小限制（批次 4 自路由层下沉）。

        Args:
            file: FastAPI UploadFile，按 10MB 分块读取。

        Returns:
            完整文件字节串。

        Raises:
            DocumentSizeExceededError: 累计读取超过 max_size。
        """
        file_content = bytearray()
        while True:
            chunk = await file.read(10 * 1024 * 1024)  # 10MB 分块读取
            if not chunk:
                break
            file_content.extend(chunk)
            if len(file_content) > max_size:
                raise DocumentSizeExceededError(
                    size=len(file_content),
                    limit=max_size,
                )
        return bytes(file_content)

    # 流式哈希读取块大小：1MB 在磁盘吞吐与 to_thread 切换频率间取平衡
    # （10MB 会让 2GB 文件的多块路径在校验前积压过多内存意图）。
    _STREAM_HASH_CHUNK = 1024 * 1024

    @staticmethod
    async def ingest_upload_stream(file, *, max_size: int) -> tuple[str, int]:
        """流式消费单个上传文件：边读边算 sha256 并硬计数，文件不进内存。

        大视频上传路径的核心读取层——UploadFile.file 是 SpooledTemporaryFile
        （>1MB 已落盘），本方法只顺序读它并回卷，内存峰值与文件大小解耦。
        sha256 计算是 CPU 密集操作，放线程池执行。

        Args:
            file: FastAPI UploadFile。
            max_size: 读取字节硬顶。Content-Length 缺失/chunked encoding/
                伪造头部时，靠这里的逐块计数兜底拒收。

        Returns:
            (file_hash, file_size)：流式 sha256 十六进制摘要与精确字节数。
            返回后流位置在 EOF，调用方复用流前须 seek(0)（MinIO 流式上传
            方法内部已统一回卷）。

        Raises:
            DocumentSizeExceededError: 累计读取超过 max_size（流被部分消费）。
        """
        import io

        def _hash_stream(stream: io.BufferedIOBase, limit: int) -> tuple[str, int]:
            hasher = hashlib.sha256()
            total = 0
            while True:
                chunk = stream.read(DocumentUploadService._STREAM_HASH_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise DocumentSizeExceededError(size=total, limit=limit)
                hasher.update(chunk)
            return hasher.hexdigest(), total

        return await asyncio.to_thread(_hash_stream, file.file, max_size)

    @classmethod
    async def read_and_validate_uploads(
        cls,
        files: list,
        *,
        allowed_extensions: set[str],
        max_size: int = 100 * 1024 * 1024,
        max_batch_count: int = 200,
    ) -> tuple[list[tuple[str, bytes]], list[dict]]:
        """批量上传预处理：类型白名单过滤 + 分块读取 + 大小限制（批次 4 自路由层下沉）。

        Returns:
            (valid_files, failed_list)：校验通过的 (filename, content) 列表与逐文件失败明细。
        """
        if len(files) > max_batch_count:
            from novamind.features.knowledge_space.exceptions import (
                DocumentCountExceededError,
            )

            raise DocumentCountExceededError(count=len(files), limit=max_batch_count)

        valid_files: list[tuple[str, bytes]] = []
        failed_list: list[dict] = []
        for file in files:
            if not file.filename:
                failed_list.append({"filename": "", "error": "文件名缺失"})
                continue
            safe_filename = os.path.basename(file.filename)
            _, ext = os.path.splitext(safe_filename.lower())
            if ext not in allowed_extensions:
                failed_list.append({
                    "filename": file.filename,
                    "error": f"不支持的文件类型: {ext}。当前支持 .pdf/.doc/.docx/.txt/.md/.csv/.html/.json/.jpg/.jpeg/.png/.gif/.webp/.mp4/.mov/.avi/.mkv/.webm/.mp3/.wav/.flac/.aac/.ogg/.m4a",
                })
                continue
            try:
                content = await cls.read_upload_file(file, max_size=max_size)
            except DocumentSizeExceededError as e:
                failed_list.append({"filename": file.filename, "error": str(e)})
                continue
            valid_files.append((file.filename, content))
        return valid_files, failed_list

    async def _normalize_upload_file(self, filename: str, file_content: bytes) -> tuple[str, bytes]:
        """.doc 自动转 .docx（OLE2 魔数前置校验），其余原样返回。"""
        ext = self._get_file_type(filename)
        if ext != "doc":
            return filename, file_content

        # CDFB（OLE2 Compound File）魔数前置校验（审计 P2）：.doc 会被交给
        # LibreOffice/Word COM 解析（转换先于 validate_file），历史 CVE 集中在
        # 文档解析器——魔数不对的字节不该喂给外部转换器。
        if not file_content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise DocumentConversionError(
                "文件扩展名为 .doc 但内容不是有效的 Word 97-2003 文档（OLE2 魔数缺失）",
                file_type="doc",
            )

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

        # 长度校验：DB 列 String(255)，超长文件名会一路穿过所有校验直到
        # INSERT 抛 1406 DataError → 500（审计 P2）。入口处显式拦截。
        if len(filename) > 255:
            raise InvalidParameterError(
                f"文件名过长（{len(filename)} 字符，上限 255）", field="filename"
            )

        # 防止路径遍历攻击
        # 允许字母、数字、中文（含扩展 A 区与兼容表意字）、CJK 标点、全角字符、
        # 下划线、连字符、空格和点。全角字符（如 ：（））不是 ASCII 路径分隔符，
        # 不构成路径遍历风险；真正的 ../、/、\ 由下方显式检查拦截。
        if not re.match(
            r"^[\w㐀-鿿豈-﫿　-〿＀-￯\-\s\.]+$",
            filename,
        ):
            raise InvalidParameterError("文件名包含非法字符", field="filename")

        # 检查路径遍历
        if ".." in filename or "/" in filename or "\\" in filename:
            raise InvalidParameterError("文件名包含非法路径字符", field="filename")

        # 获取扩展名
        ext = Path(filename).suffix.lower().lstrip(".")

        # 检查是否为支持的文件类型
        if ext not in self.SUPPORTED_FILE_TYPES:
            raise DocumentInvalidTypeError(ext)

        return ext

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

    def _get_allowed_file_types(self, kb: KnowledgeBase) -> list[str]:
        """获取允许的文件类型"""
        config = kb.get_config()
        limits = config.get("limits", {})
        return limits.get("allowed_file_types", self.SUPPORTED_FILE_TYPES)
