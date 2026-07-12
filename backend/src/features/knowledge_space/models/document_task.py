"""
Document task item model.

Compatibility note:
- class name remains `DocumentTask` for existing service code
- real table name is `document_task_items`
"""
from enum import IntEnum
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, JSON, SmallInteger, String, Text

from novamind.core.database.base import BaseModel
from novamind.shared.utils.time_utils import now_china


class TaskStatus(IntEnum):
    PENDING = 0
    PROCESSING = 1
    COMPLETED = 2
    FAILED = 3
    CANCELLED = 4


class DocumentTask(BaseModel):
    __tablename__ = "document_task_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="Task item ID")
    batch_id = Column(
        "task_id",
        BigInteger,
        ForeignKey("document_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent task ID",
    )
    document_id = Column(
        BigInteger,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Document ID",
    )
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, comment="KB ID")
    space_id = Column(BigInteger, ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, comment="Space ID")
    status = Column(SmallInteger, default=TaskStatus.PENDING, nullable=False, index=True, comment="Task item status")
    job_id = Column(String(64), nullable=True, comment="arq job ID")
    pipeline_config = Column(JSON, nullable=True, comment="Pipeline config snapshot")
    step_progress = Column(JSON, nullable=True, comment="Step progress")
    pipeline_result = Column(JSON, nullable=True, comment="Pipeline result")
    error_message = Column(Text, nullable=True, comment="Error message")
    retry_count = Column(SmallInteger, default=0, nullable=False, comment="Auto retry count")
    queued_at = Column(DateTime, nullable=True, comment="Queued at")
    started_at = Column(DateTime, nullable=True, comment="Started at")
    completed_at = Column(DateTime, nullable=True, comment="Completed at")

    __table_args__ = (
        Index("idx_task_document", "document_id"),
        Index("idx_task_kb_status", "kb_id", "status"),
        Index("idx_task_status", "status"),
        {"comment": "Document task items"},
    )

    @property
    def task_id(self) -> int:
        return self.batch_id

    def mark_processing(self) -> None:
        self.status = TaskStatus.PROCESSING
        self.started_at = now_china()

    def mark_completed(self, result: Optional[dict] = None) -> None:
        self.status = TaskStatus.COMPLETED
        self.completed_at = now_china()
        if result:
            self.pipeline_result = {**(self.pipeline_result or {}), **result}

    def mark_failed(self, error_message: str) -> None:
        self.status = TaskStatus.FAILED
        self.completed_at = now_china()
        self.error_message = error_message

    def mark_cancelled(self) -> None:
        self.status = TaskStatus.CANCELLED
        self.completed_at = now_china()

    def set_step(self, step_name: str, status: str = "done") -> None:
        self.step_progress = {**(self.step_progress or {}), step_name: status}
