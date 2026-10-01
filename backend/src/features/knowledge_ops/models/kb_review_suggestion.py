"""知识运营复审建议模型（kb-ops B2）：疑似新旧版本 / 内容矛盾的人工裁决队列。

只建议不自动（安全硬规则）：平台永不自动删改内容，建议由空间管理员
accept（触发 B1 supersede）/ dismiss 处置。
"""
from novamind.core.database.base import BaseModel
from sqlalchemy import BigInteger, Column, DateTime, Index, String, Text


class KbReviewSuggestion(BaseModel):
    """复审建议：平台生成的待人工处置条目。"""

    __tablename__ = "kb_review_suggestions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    space_id = Column(BigInteger, nullable=False, index=True, comment="所属空间ID（权限域过滤）")
    kb_id = Column(BigInteger, nullable=False, index=True, comment="所属知识库ID")

    suggestion_type = Column(
        String(32),
        nullable=False,
        comment="建议类型：new_version=疑似新旧版本 / contradiction=内容矛盾（D 批次）",
    )
    status = Column(
        String(16),
        nullable=False,
        default="open",
        comment="处置状态：open/accepted/dismissed",
    )
    score = Column(
        BigInteger,  # 相似度放大 1e4 存整（0~10000），SQLite/MySQL 通用
        nullable=True,
        comment="判定得分（0~10000，10000=完全一致）",
    )
    reason = Column(Text, nullable=True, comment="判定依据说明（展示给管理员）")

    # 涉事文档：new_version 建议 old/new 各一；contradiction 建议 doc_a/doc_b 复用此两列
    old_doc_id = Column(BigInteger, nullable=True, comment="旧版（或矛盾方 A）文档ID")
    new_doc_id = Column(BigInteger, nullable=True, comment="新版（或矛盾方 B）文档ID")

    # 处置留痕
    resolved_by = Column(BigInteger, nullable=True, comment="处置人用户ID")
    resolved_at = Column(DateTime, nullable=True, comment="处置时间")

    __table_args__ = (
        # 幂等：同 (类型, 旧, 新) 只有一条 open 建议（重复判定不重复建）。
        # 已处置的行保留历史，故唯一约束不可行，用「查询时过滤 status=open + 幂等跳过」。
        Index("idx_suggestion_space_status", "space_id", "status"),
        Index("idx_suggestion_kb_type", "kb_id", "suggestion_type"),
        {"comment": "知识运营复审建议（疑似新旧版本/内容矛盾，人工裁决队列）"},
    )

    def __repr__(self) -> str:
        return (
            f"<KbReviewSuggestion(id={self.id}, type='{self.suggestion_type}', "
            f"status='{self.status}', old={self.old_doc_id}, new={self.new_doc_id})>"
        )
