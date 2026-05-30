"""
文档模型

存储上传到知识空间的文档信息
支持知识库关联
"""
from typing import Optional, Dict, Any
from enum import IntEnum
from sqlalchemy import Column, BigInteger, SmallInteger, String, Text, DateTime, JSON, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from src.core.database.base import BaseModel
from src.shared.utils.time_utils import now_china


class DocumentStatus(IntEnum):
    """文档处理状态枚举（整数类型）"""
    UPLOADED = 0     # 已上传
    PROCESSING = 1   # 处理中
    COMPLETED = 2    # 已完成
    FAILED = 3       # 处理失败
    DELETED = 4      # 已删除


class Document(BaseModel):
    """
    文档模型

    存储上传到知识空间的文档元数据和处理状态
    """
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="文档ID")
    space_id = Column(BigInteger, ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属空间ID")
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属知识库ID")
    uploader_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True, comment="上传者用户ID")

    # 文件核心信息（需要索引，保留独立字段）
    filename = Column(String(255), nullable=False, comment="存储文件名")
    file_type = Column(String(50), nullable=False, comment="文件类型（pdf/docx/txt/md）")
    file_size = Column(BigInteger, nullable=False, comment="文件大小（字节）")
    file_hash = Column(String(64), nullable=False, index=True, comment="文件哈希值（去重）")

    # 存储配置（MinIO 相关）
    storage = Column(JSON, nullable=False, comment="存储信息（MinIO）")

    # 处理状态（整数枚举）
    status = Column(
        SmallInteger,
        default=DocumentStatus.UPLOADED,
        nullable=False,
        index=True,
        comment="状态: 0-待处理, 1-处理中, 2-已完成, 3-失败, 4-已删除"
    )

    # 状态详情
    status_info = Column(JSON, comment="状态详情（错误信息、重试次数等）")

    # 扩展信息（doc_metadata 避免 SQLAlchemy 保留字冲突）
    doc_metadata = Column(JSON, comment="文档元数据（标题、作者、标签等）")
    version_info = Column(JSON, comment="版本信息")

    # 处理时间（P1改进：独立字段，便于统计处理耗时）
    processing_started_at = Column(DateTime, nullable=True, comment="处理开始时间")
    processed_at = Column(DateTime, nullable=True, index=True, comment="处理完成时间")

    # 时间戳
    created_at = Column(DateTime, default=lambda: now_china(), nullable=False, comment="创建时间")
    updated_at = Column(
        DateTime,
        default=lambda: now_china(),
        onupdate=lambda: now_china(),
        nullable=False,
        comment="更新时间"
    )
    deleted_at = Column(DateTime, nullable=True, index=True, comment="软删除时间")

    # 索引和约束
    __table_args__ = (
        # 知识库内文件哈希唯一（防止重复上传）
        UniqueConstraint("kb_id", "file_hash", name="uq_kb_file_hash"),
        # 复合索引：知识库+状态
        Index("idx_kb_status", "kb_id", "status"),
        # 复合索引：空间+创建时间
        Index("idx_space_created", "space_id", "created_at"),
        {"comment": "文档表，存储上传到知识库的文档元数据、处理状态和存储信息"},
    )

    # 关联关系（双向：Document.knowledge_base <-> KnowledgeBase.documents）
    knowledge_base = relationship("KnowledgeBase", back_populates="documents", lazy="noload")

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, filename='{self.filename}', status={self.status})>"

    # ========== 存储信息访问方法 ==========

    def get_storage_info(self) -> dict:
        """获取存储信息"""
        return self.storage or {}

    def get_minio_bucket(self) -> Optional[str]:
        """获取 MinIO 桶名"""
        return self.get_storage_info().get("minio_bucket")

    def set_minio_info(
        self,
        bucket: str,
        object_name: str,
        etag: Optional[str] = None
    ) -> None:
        """设置 MinIO 信息"""
        self.storage = {
            **(self.storage or {}),
            "minio_bucket": bucket,
            "minio_object_name": object_name,
            "minio_etag": etag
        }

    # ========== 状态信息访问方法 ==========

    def set_error(self, error_message: str) -> None:
        """设置错误信息"""
        self.status_info = {
            **(self.status_info or {}),
            "error_message": error_message,
            "last_error_at": now_china().isoformat(),
        }

    def increment_retry(self) -> None:
        """增加重试次数"""
        self.status_info = {
            **(self.status_info or {}),
            "retry_count": (self.status_info or {}).get("retry_count", 0) + 1,
        }

    # ========== 元数据访问方法 ==========

    # ========== 版本信息访问方法 ==========

    def get_version_info(self) -> dict:
        """获取版本信息"""
        return self.version_info or {"number": 1, "parent_id": None, "comment": ""}

    def get_version_number(self) -> int:
        """获取版本号"""
        return self.get_version_info().get("number", 1)

    # ========== 状态检查方法 ==========

    # ========== 状态变更方法 ==========

    def mark_processing(self) -> None:
        """标记为处理中"""
        self.status = DocumentStatus.PROCESSING
        self.processing_started_at = now_china()
        self.status_info = {
            **(self.status_info or {}),
            "processing_started_at": self.processing_started_at.isoformat(),
        }

    def mark_completed(self) -> None:
        """标记为已完成"""
        self.status = DocumentStatus.COMPLETED
        self.processed_at = now_china()
        self.status_info = {
            **(self.status_info or {}),
            "processing_completed_at": self.processed_at.isoformat(),
        }

    def mark_failed(self, error_message: str) -> None:
        """标记为处理失败"""
        self.status = DocumentStatus.FAILED
        self.processed_at = now_china()
        self.set_error(error_message)

    # ========== 软删除方法 ==========

    def revive(self, uploader_id: int, filename: str) -> None:
        """复活已软删除的文档（用于同文件重新上传）

        重置文档状态为 UPLOADED，更新上传人信息，清除历史处理数据。
        """
        self.deleted_at = None
        self.status = DocumentStatus.UPLOADED
        self.uploader_id = uploader_id
        self.filename = filename
        self.status_info = {}
        self.doc_metadata = {}
        self.processing_started_at = None
        self.processed_at = None
