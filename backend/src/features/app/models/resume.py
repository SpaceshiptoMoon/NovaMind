"""
简历挖掘应用数据模型
"""
import uuid
from enum import IntEnum

from sqlalchemy import Column, String, Text, Integer, BigInteger, JSON, ForeignKey, Index
from novamind.core.database.base import BaseModel


def _gen_uuid():
    return str(uuid.uuid4())


class ResumeSessionStatus(IntEnum):
    DRAFT = 0
    PARSING = 1
    ANALYZING = 2
    READY = 3
    PROBING = 4
    COMPLETED = 5
    FAILED = 6


class ResumeSession(BaseModel):
    """简历解析会话"""
    __tablename__ = "resume_sessions"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)

    # 简历文件
    resume_file_url = Column(String(500), comment="MinIO 原始文件地址")
    resume_filename = Column(String(200), comment="原始文件名")

    # 结构化数据
    structured_resume = Column(JSON, comment="结构化简历数据")

    # JD（可选）
    jd_text = Column(Text, comment="岗位 JD 文本")

    # 报告
    md_report_url = Column(String(500), comment="MD 报告 MinIO 文件地址")

    # 状态
    status = Column(Integer, default=ResumeSessionStatus.DRAFT, nullable=False, comment="状态")

    # 错误信息
    error_message = Column(Text, nullable=True, comment="Pipeline 失败时的错误信息")

    # 用户配置
    config = Column(JSON, comment="用户配置(breadth, depth, llm_model)")

    __table_args__ = (
        Index("idx_resume_session_user", "user_id", "status"),
        {"comment": "简历解析会话"},
    )
