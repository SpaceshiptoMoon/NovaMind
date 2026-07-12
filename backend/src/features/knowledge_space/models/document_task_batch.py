"""
Document task parent model.

Compatibility note:
- class name remains `DocumentTaskBatch` for existing service code
- real table name is `document_tasks`
"""
from enum import IntEnum

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, JSON, SmallInteger, String, Text

from novamind.core.database.base import BaseModel
from novamind.shared.utils.time_utils import now_china


class BatchAction(IntEnum):
    PROCESS = 0
    REPROCESS = 1
    RETRY = 2


class BatchStatus(IntEnum):
    PENDING = 0
    PROCESSING = 1
    COMPLETED = 2
    FAILED = 3
    PARTIAL_FAILED = 4
    CANCELLED = 5


class DocumentTaskBatch(BaseModel):
    __tablename__ = "document_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="Task ID")
    space_id = Column(BigInteger, ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True, comment="Creator ID")
    action = Column(SmallInteger, nullable=False, default=BatchAction.PROCESS, comment="Task action")
    status = Column(SmallInteger, nullable=False, default=BatchStatus.PENDING, index=True, comment="Task status")
    pipeline_config = Column(JSON, nullable=True, comment="Pipeline config snapshot")
    total_count = Column(SmallInteger, nullable=False, default=0, comment="Document count")
    task_summary = Column(JSON, nullable=True, comment="Task summary")
    note = Column(String(255), nullable=True, comment="Task note")
    error_message = Column(Text, nullable=True, comment="Task error")
    started_at = Column(DateTime, nullable=True, comment="Started at")
    completed_at = Column(DateTime, nullable=True, comment="Completed at")

    __table_args__ = (
        Index("idx_document_task_kb_status", "kb_id", "status"),
        {"comment": "Document tasks"},
    )

    def mark_processing(self) -> None:
        self.status = BatchStatus.PROCESSING
        if self.started_at is None:
            self.started_at = now_china()

    def mark_completed(self, has_failed: bool = False) -> None:
        self.status = BatchStatus.PARTIAL_FAILED if has_failed else BatchStatus.COMPLETED
        self.completed_at = now_china()

    def mark_failed(self, error_message: str) -> None:
        self.status = BatchStatus.FAILED
        self.error_message = error_message
        self.completed_at = now_china()

    def mark_cancelled(self) -> None:
        self.status = BatchStatus.CANCELLED
        self.completed_at = now_china()
