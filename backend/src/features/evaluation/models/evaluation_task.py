"""
测评模块 ORM 模型

两张表：
- evaluation_test_sets: 测试集（可复用，文件存 MinIO）
- evaluation_tasks: 测评任务（每次执行一条记录，结果存 MinIO）
"""
from typing import Optional
from enum import IntEnum

from sqlalchemy import Column, BigInteger, SmallInteger, Integer, String, Text, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship

from novamind.core.database.base import BaseModel


class EvaluationStatus(IntEnum):
    """测评任务状态"""
    PENDING = 1
    COMPLETED = 2
    FAILED = 3
    DELETED = 4
    RUNNING = 5
    CANCELLED = 6


class EvaluationTestSet(BaseModel):
    """测试集表"""
    __tablename__ = "evaluation_test_sets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    space_id = Column(
        BigInteger,
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="所属空间 ID",
    )
    kb_id = Column(
        BigInteger,
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="所属知识库 ID",
    )
    creator_id = Column(BigInteger, nullable=False, index=True, comment="创建者 ID")
    name = Column(String(200), nullable=False, comment="测试集名称")

    # 文件信息
    filename = Column(String(255), nullable=False, comment="原始文件名")
    file_type = Column(String(50), nullable=False, comment="文件类型（json/csv）")
    file_size = Column(BigInteger, nullable=False, comment="文件大小（字节）")
    file_hash = Column(String(64), nullable=False, index=True, comment="文件 SHA-256 哈希")
    storage = Column(JSON, nullable=False, comment="MinIO 存储信息")
    total_cases = Column(Integer, nullable=False, default=0, comment="测试用例数量")

    __table_args__ = (
        Index("idx_test_set_space_kb", "space_id", "kb_id"),
        {"comment": "测试集表，存储知识库评测用的测试集文件和用例信息"},
    )

    def __repr__(self) -> str:
        return f"<EvaluationTestSet(id={self.id}, name='{self.name}', cases={self.total_cases})>"

    def get_minio_bucket(self) -> Optional[str]:
        return (self.storage or {}).get("minio_bucket")

    def get_minio_object_name(self) -> Optional[str]:
        return (self.storage or {}).get("minio_object_name")

    def set_minio_info(self, bucket: str, object_name: str, etag: Optional[str] = None) -> None:
        self.storage = {
            **(self.storage or {}),
            "minio_bucket": bucket,
            "minio_object_name": object_name,
            "minio_etag": etag,
        }


class EvaluationTask(BaseModel):
    """测评任务表"""
    __tablename__ = "evaluation_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    test_set_id = Column(
        BigInteger,
        ForeignKey("evaluation_test_sets.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="关联测试集 ID",
    )
    user_id = Column(BigInteger, nullable=False, index=True, comment="执行者 ID")
    name = Column(String(200), nullable=False, comment="任务名称")

    config = Column(JSON, comment="本次测评参数（保存以便对比）")
    status = Column(
        SmallInteger,
        default=EvaluationStatus.PENDING,
        nullable=False, index=True,
        comment="状态: 1-待执行 2-已完成 3-失败 4-已删除 5-执行中 6-已取消",
    )
    progress = Column(JSON, comment="进度信息: {current, total}")
    result_storage = Column(JSON, comment="结果文件 MinIO 存储信息")
    error_message = Column(Text, comment="错误信息")

    # 关联关系
    test_set = relationship("EvaluationTestSet", lazy="noload")

    __table_args__ = (
        Index("idx_eval_task_test_set", "test_set_id"),
        {"comment": "测评任务表，存储每次评测执行的参数、进度和结果"},
    )

    def __repr__(self) -> str:
        return f"<EvaluationTask(id={self.id}, name='{self.name}', status={self.status})>"

    def get_result_minio_bucket(self) -> Optional[str]:
        return (self.result_storage or {}).get("minio_bucket")

    def get_result_minio_object_name(self) -> Optional[str]:
        return (self.result_storage or {}).get("minio_object_name")

    def set_result_minio_info(self, bucket: str, object_name: str, etag: Optional[str] = None) -> None:
        self.result_storage = {
            **(self.result_storage or {}),
            "minio_bucket": bucket,
            "minio_object_name": object_name,
            "minio_etag": etag,
        }
