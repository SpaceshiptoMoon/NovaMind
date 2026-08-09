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


class TaskProcessMode(IntEnum):
    PROCESS = 0
    REPROCESS = 1
    RETRY = 2


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
    process_mode = Column(SmallInteger, default=TaskProcessMode.PROCESS, nullable=False, comment="Task process mode")
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
        # 成功完成即清空先前残留的瞬时错误（如 ASR 忙碌延后、自动重试记录），
        # 避免「已完成」行挂着旧 error_message 造成状态与错误信息自相矛盾。
        self.error_message = None
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
        """兼容别名：等价 finish_step(step_name)，不记 metrics/耗时。

        旧调用点传字符串 status 仅作完成标记；结构化节点日志请用 start_step/finish_step。
        """
        self.finish_step(step_name, metrics=None)

    @staticmethod
    def _duration_ms_from(started_at_str, now_dt) -> Optional[int]:
        if not started_at_str:
            return None
        try:
            from datetime import datetime
            started = datetime.fromisoformat(started_at_str)
            return int((now_dt - started).total_seconds() * 1000)
        except Exception:
            return None

    def _set_node(self, step_name: str, **fields) -> None:
        progress = dict(self.step_progress or {})
        prev = progress.get(step_name)
        base = prev if isinstance(prev, dict) else {}
        progress[step_name] = {
            "status": fields.get("status", base.get("status")),
            "started_at": fields.get("started_at", base.get("started_at")),
            "finished_at": fields.get("finished_at", base.get("finished_at")),
            "duration_ms": fields.get("duration_ms", base.get("duration_ms")),
            "metrics": fields.get("metrics", base.get("metrics", {})),
            "error": fields.get("error", base.get("error")),
        }
        self.step_progress = progress

    def start_step(self, step_name: str) -> None:
        """记录节点开始：status=running + started_at。"""
        self._set_node(
            step_name, status="running", started_at=now_china().isoformat(),
            finished_at=None, duration_ms=None, metrics={}, error=None,
        )

    def finish_step(self, step_name: str, metrics: Optional[dict] = None) -> None:
        """记录节点完成：status=done + finished_at + duration_ms + metrics。"""
        now = now_china()
        prev = self.step_progress.get(step_name) if self.step_progress else None
        started_at_str = prev.get("started_at") if isinstance(prev, dict) else None
        self._set_node(
            step_name, status="done", finished_at=now.isoformat(),
            duration_ms=self._duration_ms_from(started_at_str, now),
            metrics=metrics or {}, error=None,
        )

    def fail_step(self, step_name: str, error: str) -> None:
        """记录节点失败：status=failed + finished_at + duration_ms + error。"""
        now = now_china()
        prev = self.step_progress.get(step_name) if self.step_progress else None
        started_at_str = prev.get("started_at") if isinstance(prev, dict) else None
        prev_metrics = prev.get("metrics") if isinstance(prev, dict) else {}
        self._set_node(
            step_name, status="failed", finished_at=now.isoformat(),
            duration_ms=self._duration_ms_from(started_at_str, now),
            metrics=prev_metrics or {}, error=error,
        )

    def mark_last_running_step_failed(self, error: str) -> None:
        """把最后一个 status=running 的节点标记为 failed + error。

        任务整体失败时调用，让节点日志显示「卡在哪个节点」。无 running 节点则 noop。
        """
        progress = self.step_progress or {}
        last_running = None
        for name, entry in progress.items():
            if isinstance(entry, dict) and entry.get("status") == "running":
                last_running = name
        if last_running:
            self.fail_step(last_running, error)
