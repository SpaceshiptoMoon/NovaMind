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
from novamind.features.agent.exceptions import (
    AttachmentNotFoundError,
    AttachmentUploadError,
)
from novamind.features.agent.attachments.repository import ChatAttachmentRepository
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.features.user.services.search_config_service import SearchConfigService
from novamind.shared.storage.minio_client import IMAGE_FILE_TYPES
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from novamind.engines.document.pipeline import DocumentProcessor
    from novamind.features.knowledge_space.services.search_service import SearchService
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
        model_config_service: ModelConfigService | None = None,
        db: AsyncSession | None = None,
        minio_client: Optional["MinioClient"] = None,
        search_service: Optional["SearchService"] = None,
        document_processor: Optional["DocumentProcessor"] = None,
        search_config_service: SearchConfigService | None = None,
    ):
        """
        初始化附件服务

        Args:
            model_config_service: 模型配置服务（保留装配面兼容，附件链未消费）
            db: 数据库会话（用于附件存储）
            minio_client: MinIO 客户端（用于文件存储）
            search_service: 检索服务（保留装配面兼容，附件链未消费）
            document_processor: 文档摄入处理器（DocumentProcessor 引擎实例）
            search_config_service: 用户搜索配置服务（保留装配面兼容，附件链未消费）
        """
        self.model_config_service = model_config_service
        self.db = db
        self.minio_client = minio_client
        self.attachment_repo = ChatAttachmentRepository(db) if db else None
        self.logger = get_logger(__name__)
        self._search_service = search_service
        self._document_processor = document_processor
        self._search_config_service = search_config_service

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

        # 验证文件内容（魔术字节校验，防止文件伪装攻击）
        from novamind.shared.document.validation import validate_file
        file_info = validate_file(
            content=file_data,
            filename=filename,
            allowed_extensions=self.ALLOWED_FILE_TYPES,
        )
        if not file_info.is_valid:
            raise InvalidMessageContentError(f"文件内容与类型不匹配: {file_info.validation_message}")

        # 上传到 MinIO
        storage_path = f"chat-attachments/{user_id}/{uuid4().hex}.{ext}"
        content_type = self.minio_client._get_content_type(filename)
        await self.minio_client.upload_file(storage_path, file_data, content_type)
        self.logger.info("附件已上传到 MinIO", user_id=user_id, path=storage_path, size=len(file_data))

        # 提取文本（图片类型跳过）
        extracted_text = None
        if ext not in self.IMAGE_FILE_TYPES:
            try:
                extracted_text = await self._extract_text_from_bytes(file_data, ext)
                if extracted_text and len(extracted_text) > self.MAX_EXTRACTED_TEXT_LENGTH:
                    extracted_text = extracted_text[:self.MAX_EXTRACTED_TEXT_LENGTH] + "\n\n[... 文档内容已截断 ...]"
            except Exception as e:
                self.logger.warning("提取文档文本失败", filename=filename, error=str(e))

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
            "message": "附件上传成功" if extracted_text else "附件上传成功，但文本提取失败",
        }

    async def _extract_text_from_bytes(self, file_data: bytes, file_type: str) -> str | None:
        """从文件字节中提取文本"""
        if file_type in ("txt", "md"):
            # 文本文件直接解码
            for encoding in ("utf-8", "gbk", "gb2312", "latin-1"):
                try:
                    return file_data.decode(encoding)
                except (UnicodeDecodeError, LookupError):
                    continue
            return None

        # PDF / DOCX 经 DocumentProcessor 引擎处理（R1 下直接消费引擎，无需宿主包装）
        document_processor = self._document_processor

        with tempfile.NamedTemporaryFile(suffix=f".{file_type}", delete=False) as tmp:
            tmp.write(file_data)
            tmp_path = tmp.name

        try:
            docs = await document_processor.load_with_strategy(
                tmp_path,
                strategy="recursive",
                chunk_size=10000,
                chunk_overlap=0,
            )
            texts = [doc.get("text", "") or doc.get("content", "") for doc in docs]
            return "\n\n".join(texts) if texts else None
        finally:
            os.unlink(tmp_path)
