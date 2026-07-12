"""
会话摘要模型

存储压缩后的对话摘要，支持摘要历史追溯
"""

from typing import Optional
from sqlalchemy import Column, BigInteger, Integer, String, Text, JSON, ForeignKey

from novamind.core.database.base import BaseModel


class SessionSummary(BaseModel):
    """
    会话摘要模型

    存储压缩后的对话摘要
    """
    __tablename__ = "qa_session_summaries"
    __table_args__ = (
        {"comment": "QA 会话摘要表，存储压缩后的对话摘要和版本信息"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(36), nullable=False, index=True, comment="会话ID")
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, comment="用户ID")

    # 核心内容
    summary_content = Column(Text, nullable=False, comment="摘要内容")

    # 统计信息（需要频繁查询，保留独立字段）
    summary_tokens = Column(Integer, default=0, nullable=False, comment="摘要 token 数")
    compressed_message_count = Column(Integer, default=0, nullable=False, comment="被压缩的消息数量")
    original_tokens = Column(Integer, default=0, nullable=False, comment="压缩前的 token 数")
    last_compressed_message_id = Column(BigInteger, nullable=True, comment="最后被压缩的消息ID")

    # 其他统计信息合并为 JSON
    stats = Column(JSON, comment="其他统计信息")

    # 版本控制
    last_message_id = Column(BigInteger, nullable=False, comment="最后处理的消息ID")
    version = Column(Integer, default=1, nullable=False, comment="版本号")

    # 时间戳：直接使用 BaseModel 默认的 now_china()，不再覆盖

    def __repr__(self) -> str:
        return f"<SessionSummary(session_id={self.session_id}, version={self.version})>"

    # ========== Stats 访问方法 ==========

    def get_summary_tokens(self) -> int:
        """获取摘要 token 数"""
        return self.summary_tokens or 0

    def get_original_tokens(self) -> int:
        """获取压缩前的 token 数"""
        return self.original_tokens or 0

    def get_compression_ratio(self) -> float:
        """计算压缩比"""
        original = self.get_original_tokens()
        summary = self.get_summary_tokens()
        if original > 0:
            return summary / original
        return 1.0

