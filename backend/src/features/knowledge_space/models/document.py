"""
文档模型

存储上传到知识空间的文档元数据。
处理状态与生命周期追踪已迁移至 DocumentTaskItem 模型。
"""
from typing import Optional
from enum import IntEnum
from sqlalchemy import Column, BigInteger, String, DateTime, JSON, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from src.core.database.base import BaseModel


# 保留此枚举用于过渡期兼容 — 旧代码仍可导入，但 Document 模型本身不再使用
# 新代码应使用 TaskStatus（models/document_task.py）
class DocumentStatus(IntEnum):
    """文档处理状态枚举（已废弃，保留用于向后兼容）"""
    UPLOADED = 0     # 已上传 → 请用 TaskStatus.PENDING
    PROCESSING = 1   # 处理中 → 请用 TaskStatus.PROCESSING
    COMPLETED = 2    # 已完成 → 请用 TaskStatus.COMPLETED
    FAILED = 3       # 处理失败 → 请用 TaskStatus.FAILED
    DELETED = 4      # 已删除 → Document.deleted_at


class Document(BaseModel):
    """
    文档模型 — 纯文件元数据

    仅存储文件本身的信息。处理状态、重试、错误等全部由 DocumentTaskItem 管理。
    """
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="文档ID")
    space_id = Column(BigInteger, ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属空间ID")
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属知识库ID")
    uploader_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True, comment="上传者用户ID")

    # 文件核心信息
    filename = Column(String(255), nullable=False, comment="存储文件名")
    file_type = Column(String(50), nullable=False, comment="文件类型（pdf/docx/txt/md）")
    file_size = Column(BigInteger, nullable=False, comment="文件大小（字节）")
    file_hash = Column(String(64), nullable=False, index=True, comment="文件哈希值（去重）")

    # 存储信息（MinIO 路径 + parsed_text_object）
    storage = Column(JSON, nullable=False, default=dict, comment="存储信息（MinIO）")

    deleted_at = Column(DateTime, nullable=True, index=True, comment="软删除时间")

    # 索引和约束
    __table_args__ = (
        UniqueConstraint("kb_id", "file_hash", name="uq_kb_file_hash"),
        Index("idx_space_created", "space_id", "created_at"),
        {"comment": "文档表，存储文件元数据；处理状态见 document_task_items 表"},
    )

    # 关联关系
    knowledge_base = relationship("KnowledgeBase", back_populates="documents", lazy="noload")
    tasks = relationship("DocumentTaskItem", back_populates="document", lazy="noload", order_by="DocumentTaskItem.id.desc()")

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, filename='{self.filename}')>"

    # ========== 存储信息 ==========

    def get_storage_info(self) -> dict:
        """获取存储信息"""
        return self.storage or {}

    def get_minio_bucket(self) -> Optional[str]:
        """获取 MinIO 桶名"""
        return self.get_storage_info().get("minio_bucket")

    def set_minio_info(self, bucket: str, object_name: str, etag: Optional[str] = None) -> None:
        """设置 MinIO 信息"""
        self.storage = {
            **(self.storage or {}),
            "minio_bucket": bucket,
            "minio_object_name": object_name,
            "minio_etag": etag,
        }

    # ========== 软删除 ==========

    def undelete(self, uploader_id: int, filename: str) -> None:
        """复活已软删除的文档（同文件重新上传）

        仅清除软删除标记并更新上传者/文件名。处理任务由调用方另行创建。
        """
        self.deleted_at = None
        self.uploader_id = uploader_id
        self.filename = filename
