"""
问答记录模型

支持知识库关联和空间关联
"""
from typing import Optional
from sqlalchemy import Column, BigInteger, String, Text, JSON, ForeignKey, Index

from src.core.database.base import BaseModel


class QuestionAnswer(BaseModel):
    """
    问答记录模型

    支持知识库关联和空间关联
    """
    __tablename__ = "question_answers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True, comment="用户ID")
    session_id = Column(String(36), nullable=False, index=True, comment="会话ID")

    # 关联知识空间（可选）
    space_id = Column(
        BigInteger,
        ForeignKey("knowledge_spaces.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="所属空间ID",
    )

    # 关联知识库（可选）
    kb_id = Column(
        BigInteger,
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联知识库ID（可选）",
    )

    # 消息内容
    role = Column(String(20), nullable=False, comment="user/assistant/system")
    content = Column(Text, nullable=False, comment="消息内容")

    # 扩展信息（合并为 JSON）
    extra = Column(JSON, comment="扩展信息（反馈、Token统计等）")

    # 时间戳：直接使用 BaseModel 默认的 now_china()，不再覆盖

    # 复合索引
    __table_args__ = (
        Index("idx_session_created", "session_id", "created_at"),
        {"comment": "问答记录表，存储用户与系统的对话消息和扩展信息"},
    )

    def __repr__(self) -> str:
        return f"<QuestionAnswer(id={self.id}, session_id={self.session_id}, role='{self.role}')>"

    # ========== Extra 访问方法 ==========

    def get_extra(self) -> dict:
        """获取扩展信息"""
        return self.extra or {}

    def get_feedback(self) -> dict:
        """获取反馈信息"""
        return self.get_extra().get("feedback", {})

    def get_usage(self) -> dict:
        """获取Token统计"""
        return self.get_extra().get("usage", {})

    def get_references(self) -> list:
        """获取引用来源"""
        return self.get_extra().get("references", [])

    def set_feedback(self, rating: Optional[int] = None, comment: Optional[str] = None, helpful: Optional[bool] = None) -> None:
        """设置反馈"""
        extra = self.get_extra()
        if "feedback" not in extra:
            extra["feedback"] = {}
        if rating is not None:
            extra["feedback"]["rating"] = rating
        if comment is not None:
            extra["feedback"]["comment"] = comment
        if helpful is not None:
            extra["feedback"]["helpful"] = helpful
        self.extra = extra

    def set_usage(self, input_tokens: int, output_tokens: int, model: Optional[str] = None) -> None:
        """设置Token统计"""
        extra = self.get_extra()
        extra["usage"] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        }
        if model:
            extra["usage"]["model"] = model
        self.extra = extra

    def set_references(self, references: list) -> None:
        """设置引用来源"""
        extra = self.get_extra()
        extra["references"] = references
        self.extra = extra

    def get_input_tokens(self) -> int:
        """获取输入Token数"""
        return self.get_usage().get("input_tokens", 0)

    def get_output_tokens(self) -> int:
        """获取输出Token数"""
        return self.get_usage().get("output_tokens", 0)

    def get_attachments(self) -> list:
        """获取附件信息"""
        return self.get_extra().get("attachments", [])

    def set_attachments(self, attachments: list) -> None:
        """设置附件信息"""
        extra = self.get_extra()
        extra["attachments"] = attachments
        self.extra = extra
