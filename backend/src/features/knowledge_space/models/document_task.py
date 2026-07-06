"""
DocumentTask 模型

文档处理任务追踪 — 记录每个文档的处理全过程。
从 Document 模型中分离出来，Document 只管文件元数据。
"""
from typing import Optional
from enum import IntEnum
from sqlalchemy import Column, BigInteger, SmallInteger, String, Text, DateTime, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship
from src.core.database.base import BaseModel
from src.shared.utils.time_utils import now_china


class TaskStatus(IntEnum):
    """任务处理状态枚举"""
    PENDING = 0       # 待处理（已入队，等待 Worker 取出）
    PROCESSING = 1    # 处理中
    COMPLETED = 2     # 已完成
    FAILED = 3        # 失败
    CANCELLED = 4     # 已取消


class DocumentTask(BaseModel):
    """
    文档处理任务模型

    一次文档处理（process/reprocess/retry）对应一条 Task 记录。
    记录完整的处理生命周期：配置快照 → 步骤进度 → 结果/错误。
    """
    __tablename__ = "document_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="任务ID")
    document_id = Column(
        BigInteger,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联文档ID",
    )
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, comment="知识库ID（冗余）")
    space_id = Column(BigInteger, ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, comment="空间ID（冗余）")

    # 状态
    status = Column(
        SmallInteger,
        default=TaskStatus.PENDING,
        nullable=False,
        index=True,
        comment="状态: 0-待处理, 1-处理中, 2-已完成, 3-失败, 4-已取消",
    )
    job_id = Column(String(64), nullable=True, comment="arq job ID")

    # 配置快照 — 处理开始时 KB.config 的完整拷贝
    pipeline_config = Column(JSON, nullable=True, comment="处理配置快照（KB.config 副本）")

    # 步骤进度 — 记录每个阶段的完成状态
    step_progress = Column(JSON, nullable=True, comment="步骤进度: {parsed, split, embedded, indexed}")

    # 处理结果
    pipeline_result = Column(JSON, nullable=True, comment="处理结果: {chunk_count, segment_count, frame_count, ...}")

    # 错误
    error_message = Column(Text, nullable=True, comment="错误信息")
    retry_count = Column(SmallInteger, default=0, nullable=False, comment="重试次数")

    # 时间
    queued_at = Column(DateTime, nullable=True, comment="入队时间")
    started_at = Column(DateTime, nullable=True, comment="开始处理时间")
    completed_at = Column(DateTime, nullable=True, comment="完成/失败时间")

    # 标准时间戳
    created_at = Column(DateTime, default=lambda: now_china(), nullable=False, comment="创建时间")
    updated_at = Column(
        DateTime,
        default=lambda: now_china(),
        onupdate=lambda: now_china(),
        nullable=False,
        comment="更新时间",
    )

    # 关系
    document = relationship("Document", back_populates="tasks", lazy="noload")

    # 索引
    __table_args__ = (
        Index("idx_task_document", "document_id"),
        Index("idx_task_kb_status", "kb_id", "status"),
        Index("idx_task_status", "status"),
        {"comment": "文档处理任务表，记录每次处理的完整生命周期"},
    )
    # 注意：并发防护通过应用层 check（查询是否有 PENDING/PROCESSING 的 Task）+ DB 唯一约束
    # MySQL 不支持 partial index，如需 DB 级防护可加普通索引 + 应用层校验

    def __repr__(self) -> str:
        return f"<DocumentTask(id={self.id}, doc={self.document_id}, status={self.status})>"

    # ========== 状态变更方法 ==========

    def mark_processing(self) -> None:
        """标记为处理中"""
        self.status = TaskStatus.PROCESSING
        self.started_at = now_china()

    def mark_completed(self, result: Optional[dict] = None) -> None:
        """标记为已完成"""
        self.status = TaskStatus.COMPLETED
        self.completed_at = now_china()
        if result:
            self.pipeline_result = {**(self.pipeline_result or {}), **result}

    def mark_failed(self, error_message: str) -> None:
        """标记为失败"""
        self.status = TaskStatus.FAILED
        self.completed_at = now_china()
        self.error_message = error_message

    def mark_cancelled(self) -> None:
        """标记为已取消"""
        self.status = TaskStatus.CANCELLED
        self.completed_at = now_china()

    def set_step(self, step_name: str, status: str = "done") -> None:
        """记录步骤进度"""
        self.step_progress = {**(self.step_progress or {}), step_name: status}
