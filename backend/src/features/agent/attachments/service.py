"""聊天附件服务：上传/下载/文本提取（agent 对话与 QA 归档共享的附件基础设施）。

批4 工作台统一后对话唯一入口是 agent 对话面，本服务收缩为纯附件链：
物理存储在 chat_attachments 表 + MinIO，agent 前端（stores/agent.ts）与
后端（features/agent/chat_service._prepare）按 user_id 维度引用附件 id，
不做会话级归属校验——同一用户可跨会话/跨 agent 复用附件，为既有设计
决策。孤儿回收由 cron 任务 cleanup_orphan_attachments 负责。
"""
import os
import tempfile
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

from fastapi import UploadFile
from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent.attachments.repository import ChatAttachmentRepository
from novamind.features.agent.exceptions import (
    AttachmentNotFoundError,
    AttachmentUploadError,
    InvalidMessageContentError,
)
from novamind.shared.storage.minio_client import IMAGE_FILE_TYPES
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from novamind.engines.document.pipeline import DocumentProcessor
    from novamind.shared.storage.minio_client import MinioClient


class AttachmentService:
    """附件服务：上传（类型/魔数校验 + MinIO 存储 + 文本提取）与归属下载。"""

    # 允许的文件类型及扩展名
    ALLOWED_FILE_TYPES = {"pdf", "docx", "txt", "md", "markdown", "jpg", "jpeg", "png", "gif", "webp"}
    IMAGE_FILE_TYPES = IMAGE_FILE_TYPES  # 收敛到 minio_client 唯一定义
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
    MAX_EXTRACTED_TEXT_LENGTH = 50000  # 50000 字符

    def __init__(
        self,
        db: AsyncSession | None = None,
        minio_client: Optional["MinioClient"] = None,
        document_processor: Optional["DocumentProcessor"] = None,
    ):
        """
        初始化附件服务

        Args:
            db: 数据库会话（用于附件存储）
            minio_client: MinIO 客户端（用于文件存储）
            document_processor: 文档摄入处理器（DocumentProcessor 引擎实例，
                pdf/docx 文本提取必需；历史缺陷：装配点漏传导致提取静默失败，
                DI 门禁按语义必填检查本参——见
                tests/architecture/test_di_wiring_completeness.py）
        """
        self.db = db
        self.minio_client = minio_client
        self.attachment_repo = ChatAttachmentRepository(db) if db else None
        self.logger = get_logger(__name__)
        self._document_processor = document_processor

    async def get_attachment_content(self, attachment_id: int, user_id: int) -> tuple[Any, bytes]:
        """按用户校验归属后取回附件记录与文件内容。

        Args:
            attachment_id: 附件 ID。
            user_id: 请求者用户 ID，与附件归属不一致按不存在处理（不泄漏存在性）。

        Returns:
            (attachment, file_content) 二元组，附件记录与 MinIO 原始字节。

        Raises:
            AttachmentUploadError: 附件服务未初始化。
            AttachmentNotFoundError: 附件不存在或不属于该用户。
        """
        if not self.attachment_repo or not self.minio_client:
            raise AttachmentUploadError("附件服务未初始化")

        attachment = await self.attachment_repo.get_by_id(attachment_id)
        if not attachment or attachment.user_id != user_id:
            raise AttachmentNotFoundError(attachment_id)

        file_content = await self.minio_client.download_document(
            self.minio_client.default_bucket,
            attachment.storage_path,
        )
        return attachment, file_content

    async def upload_attachment(
        self,
        user_id: int,
        file: UploadFile,
    ) -> dict[str, Any]:
        """
        上传聊天附件

        Args:
            user_id: 用户ID
            file: 上传的文件

        Returns:
            上传结果（attachment_id, filename, file_type, file_size, status, message）
        """
        if not self.db or not self.minio_client:
            raise AttachmentUploadError("附件上传服务未初始化")

        # 验证文件类型
        filename = file.filename or "unknown"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "markdown":
            ext = "md"
        if ext not in self.ALLOWED_FILE_TYPES:
            raise InvalidMessageContentError(f"不支持的文件类型: {ext}，仅支持 {', '.join(sorted(self.ALLOWED_FILE_TYPES))}")

        # 读取文件内容
        file_data = await file.read()
        if len(file_data) > self.MAX_FILE_SIZE:
            raise InvalidMessageContentError(f"文件过大: {len(file_data)} 字节，最大允许 {self.MAX_FILE_SIZE // (1024*1024)}MB")

        # 验证文件内容（魔术字节校验，防止文件伪装攻击）：传归一后的文件名，
        # 保证白名单判定与魔数/文本类分治判定使用同一扩展名语义（.markdown→md，
        # 否则 markdown 落在文本类白名单外会被误拒）
        from novamind.shared.document.validation import validate_file
        normalized_filename = f"{filename.rsplit('.', 1)[0]}.{ext}"
        file_info = validate_file(
            content=file_data,
            filename=normalized_filename,
            allowed_extensions=self.ALLOWED_FILE_TYPES,
        )
        if not file_info.is_valid:
            raise InvalidMessageContentError(f"文件内容与类型不匹配: {file_info.validation_message}")

        # 上传到 MinIO
        storage_path = f"chat-attachments/{user_id}/{uuid4().hex}.{ext}"
        content_type = self.minio_client._get_content_type(filename)
        await self.minio_client.upload_file(storage_path, file_data, content_type)
        self.logger.info("附件已上传到 MinIO", user_id=user_id, path=storage_path, size=len(file_data))

        # 提取文本（图片类型跳过）：状态显式化（skipped/ok/empty/failed）——
        # 静默 None 会让附件「上传成功但永远读不到内容」且无从补救
        extracted_text = None
        extraction_status = "skipped"  # 图片无文本提取
        if ext not in self.IMAGE_FILE_TYPES:
            try:
                extracted_text = await self._extract_text_from_bytes(file_data, ext)
                if extracted_text and len(extracted_text) > self.MAX_EXTRACTED_TEXT_LENGTH:
                    extracted_text = extracted_text[:self.MAX_EXTRACTED_TEXT_LENGTH] + "\n\n[... 文档内容已截断 ...]"
                extraction_status = "ok" if extracted_text else "empty"
            except Exception as e:
                extraction_status = "failed"
                self.logger.warning(
                    "提取文档文本失败（附件正文不可读，可经 reextract 端点补救）",
                    filename=filename, error=str(e),
                )

        # 创建数据库记录
        attachment = await self.attachment_repo.create(
            user_id=user_id,
            filename=filename,
            file_type=ext,
            file_size=len(file_data),
            storage_path=storage_path,
            extracted_text=extracted_text,
        )

        self.logger.info(
            "聊天附件创建成功",
            attachment_id=attachment.id,
            filename=filename,
            text_length=len(extracted_text) if extracted_text else 0,
        )

        return {
            "attachment_id": attachment.id,
            "filename": filename,
            "file_type": ext,
            "file_size": len(file_data),
            "extraction_status": extraction_status,
            "message": {
                "ok": "附件上传成功",
                "empty": "附件上传成功，但未提取到文本内容（扫描件请走知识库解析）",
                "failed": "附件上传成功，但文本提取失败（可稍后重试提取）",
                "skipped": "图片上传成功",
            }[extraction_status],
        }

    async def _extract_text_from_bytes(self, file_data: bytes, file_type: str) -> str | None:
        """从文件字节中提取文本。

        Args:
            file_data: 文件字节内容。
            file_type: 归一后的扩展名（txt/md/pdf/docx）。

        Returns:
            提取的全文；无可提取内容（含扫描件 PDF 空文字层）返回 None。

        Raises:
            AttachmentUploadError: DocumentProcessor 未装配——装配断线曾让
                pdf/docx 提取整体静默失败，显式抛出优于静默 None。
        """
        if file_type in ("txt", "md"):
            # 文本文件直接解码
            for encoding in ("utf-8", "gbk", "gb2312", "latin-1"):
                try:
                    return file_data.decode(encoding)
                except (UnicodeDecodeError, LookupError):
                    continue
            return None

        if self._document_processor is None:
            raise AttachmentUploadError("DocumentProcessor 未装配，pdf/docx 文本提取不可用")

        # PDF / DOCX 经 DocumentProcessor 引擎读取全文（reader-only 不切分，
        # 附件消费方 read_attachment 只需全文；扫描件 PDF 文字层为空时引擎
        # 告警并返回空文本，不做 OCR 兜底——失败方向是「无内容」非「错内容」）
        with tempfile.NamedTemporaryFile(suffix=f".{file_type}", delete=False) as tmp:
            tmp.write(file_data)
            tmp_path = tmp.name

        try:
            full_text = await self._document_processor.read_full_text(tmp_path)
            return full_text if full_text and full_text.strip() else None
        finally:
            os.unlink(tmp_path)

    async def reextract_attachment(self, user_id: int, attachment_id: int) -> dict[str, Any]:
        """重新提取附件正文（修复提取失败期的残废附件：extracted_text 为空的非图片记录）。

        Args:
            user_id: 请求者用户 ID，与附件归属不符按不存在处理。
            attachment_id: 附件 ID。

        Returns:
            含 attachment_id/filename/extraction_status/message 的结果 dict。

        Raises:
            AttachmentUploadError: 附件服务未初始化。
            AttachmentNotFoundError: 附件不存在或不属于该用户。
            InvalidMessageContentError: 图片附件无正文可提取。
        """
        if not self.attachment_repo or not self.minio_client:
            raise AttachmentUploadError("附件服务未初始化")

        attachment = await self.attachment_repo.get_by_id(attachment_id)
        if not attachment or attachment.user_id != user_id:
            raise AttachmentNotFoundError(attachment_id)
        if attachment.file_type in self.IMAGE_FILE_TYPES:
            raise InvalidMessageContentError("图片附件无正文可提取")

        file_content = await self.minio_client.download_document(
            self.minio_client.default_bucket,
            attachment.storage_path,
        )
        try:
            extracted_text = await self._extract_text_from_bytes(file_content, attachment.file_type)
            if extracted_text and len(extracted_text) > self.MAX_EXTRACTED_TEXT_LENGTH:
                extracted_text = extracted_text[:self.MAX_EXTRACTED_TEXT_LENGTH] + "\n\n[... 文档内容已截断 ...]"
            status = "ok" if extracted_text else "empty"
        except Exception as e:
            status = "failed"
            self.logger.warning(
                "重新提取附件文本失败", attachment_id=attachment_id, error=str(e),
            )
            extracted_text = None

        await self.attachment_repo.update_extracted_text(attachment_id, extracted_text)
        return {
            "attachment_id": attachment_id,
            "filename": attachment.filename,
            "extraction_status": status,
            "message": {
                "ok": "文本提取成功",
                "empty": "未提取到文本内容（扫描件 PDF 请走知识库 DeepDoc 策略）",
                "failed": "文本提取失败，请稍后重试",
            }[status],
        }
