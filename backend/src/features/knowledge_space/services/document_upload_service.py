"""文档上传服务（从 document_service.py 巨石抽出的上传职责）。

集中承载文档上传校验与 MinIO 落库（不触发解析）：
- ``upload_document`` / ``upload_documents``：单/批量上传，仅存 MinIO，不触发解析
- ``_normalize_upload_file``：.doc → .docx 自动转换
- ``_get_file_type`` / ``_get_max_file_size`` / ``_get_allowed_file_types``：上传校验三件套
- ``_compute_sha256``：文件哈希（CPU 密集，调用方放线程池）

文件类型常量与模态映射收敛到 ``document_file_types``（中立模块）。
"""

from typing import Optional, List, Dict, Any
import asyncio
import hashlib
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.repository.space_repository import SpaceRepository
from novamind.features.knowledge_space.services.permission_service import PermissionService
from novamind.features.knowledge_space.exceptions import (
    KnowledgeBaseNotFoundError,
    DocumentAlreadyExistsError,
    DocumentConversionError,
    DocumentInvalidTypeError,
    DocumentSizeExceededError,
    InvalidParameterError,
    SpaceAccessDeniedError,
)
from novamind.shared.storage.minio_client import MinioClient
from novamind.features.knowledge_space.converters.doc_converter import (
    convert_doc_to_docx,
    DocConversionError,
)
from novamind.shared.document.validation import validate_file
from novamind.features.knowledge_space.schemas.document_schema import UploadedDocumentResult
from novamind.core.middleware.structured_logging import get_logger

from novamind.features.knowledge_space.services.document_file_types import (
    SUPPORTED_FILE_TYPES,
    MODALITY_TO_FILE_TYPES,
)


def _compute_sha256(content: bytes) -> str:
    """计算 SHA256 哈希（CPU 密集操作，用于在线程池中执行）"""
    return hashlib.sha256(content).hexdigest()


class DocumentUploadService:
    """文档上传服务：校验 + MinIO 落库（不触发解析）。"""

    # 文件类型常量收敛到 document_file_types（upload 校验引用）
    from novamind.features.knowledge_space.services.document_file_types import (
        SUPPORTED_FILE_TYPES,
        MODALITY_TO_FILE_TYPES,
    )

    # 各模态默认最大文件大小（MB）
    _MODALITY_MAX_SIZE_MB = {"text": 100, "image": 100, "video": 500, "audio": 200}

    def __init__(self, session: AsyncSession, minio_client: MinioClient):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.kb_repo = KnowledgeBaseRepository(session)
        self.space_repo = SpaceRepository(session)
        self.minio_client = minio_client
        self.logger = get_logger(__name__)
        self.member_repo = MemberRepository(session)
        self.permission_service = PermissionService()

    async def upload_document(
        self,
        kb_id: int,
        uploader_id: int,
        file_content: bytes,
        filename: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> UploadedDocumentResult:
        """
        上传文档（仅存 MinIO，不触发解析）

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
            raise DocumentInvalidTypeError(f"{file_info.extension}: {file_info.validation_message}")

        # 5.5 根据知识库模态校验文件类型
        file_type = file_info.extension
        from novamind.features.knowledge_space.services.knowledge_base_service import (
            get_effective_space_types,
        )

        await self.space_repo.get_by_id(kb.space_id)
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
            # 在 session 仍活跃时把标量读入 DTO，避免后续 rollback expire 实例。
            return UploadedDocumentResult(
                document_id=soft_deleted.id,
                filename=soft_deleted.filename,
                file_size=soft_deleted.file_size,
            )

        # 9. 创建文档记录 + 上传 MinIO（使用 SAVEPOINT 保证原子性）
        # 注意：doc_repo.create 先 flush 出真实 document_id 再上传 MinIO，因此
        # 唯一约束冲突（uq_kb_file_hash）发生在 flush 阶段、MinIO 上传之前，
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
        except IntegrityError:
            # uq_kb_file_hash 冲突：同知识库已存在相同哈希的文档。正常情况下步骤 8 的
            # 去重检查会先命中并抛出 DocumentAlreadyExistsError，这里只兜底两类漏网
            # 场景——(a) 哈希缓存残留 exists=False 导致 get_by_hash 跳过 DB 查询，
            # (b) 并发上传竞争。SAVEPOINT 已自动回滚，再抛业务异常避免 500。
            await self.session.rollback()
            raise DocumentAlreadyExistsError(filename)

        # 创建成功后同步哈希缓存为 exists=True。步骤 8 的 get_by_hash 在未命中时会
        # 缓存 exists=False，若创建后不更正，后续同哈希上传会因缓存命中而绕过去重
        # 检查、直接撞上 uq_kb_file_hash 唯一约束（正是批量重传时的 IntegrityError）。
        await self.doc_repo.cache_document_hash(kb_id, file_hash, exists=True)

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
            {"success": [UploadedDocumentResult, ...], "failed": [{"filename": str, "error": str}, ...]}
        """
        success: List[UploadedDocumentResult] = []
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
        if not re.match(r"^[\w一-龥\-\s\.]+$", filename):
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

    def _get_allowed_file_types(self, kb: KnowledgeBase) -> List[str]:
        """获取允许的文件类型"""
        config = kb.get_config()
        limits = config.get("limits", {})
        return limits.get("allowed_file_types", self.SUPPORTED_FILE_TYPES)
