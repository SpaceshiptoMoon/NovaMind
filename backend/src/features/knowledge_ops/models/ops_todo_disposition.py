"""运营待办处置状态：忽略/完成的轻量持久层（非物化待办表）。

三源待办（gap/复审/低分反馈）保持即时聚合、各有权威数据源，本表只存
「人对某条待办做过什么处置」这一状态，让忽略跨会话/跨用户/跨设备可见。
撤销忽略 = 删行（事件账本已有 todo_ignored/todo_unignored 留痕，无需软删）。
"""
from novamind.core.database.base import BaseModel
from sqlalchemy import BigInteger, Column, Index, String, UniqueConstraint


class OpsTodoDisposition(BaseModel):
    """待办处置状态行：(space, todo_key) 唯一。

    todo_key 编码与收件箱聚合约定一致：gap=聚簇归一键（截 128）、
    review=文档 ID、feedback=消息 ID——忽略写入与待办生成必须同键。
    """

    __tablename__ = "ops_todo_dispositions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    space_id = Column(BigInteger, nullable=False, index=True, comment="空间ID")
    todo_key = Column(String(512), nullable=False, comment="待办唯一键（与三源聚合约定同编码）")
    kind = Column(String(16), nullable=False, comment="待办类型：gap/review/feedback")
    status = Column(String(16), nullable=False, default="ignored", comment="处置状态：ignored（预留 done）")
    reason = Column(String(32), nullable=True, comment="忽略原因：one_shot/non_kb/false_positive")
    operator_id = Column(BigInteger, nullable=False, index=True, comment="处置人用户ID")

    __table_args__ = (
        UniqueConstraint("space_id", "todo_key", name="uq_todo_disposition_space_key"),
        Index("idx_todo_disposition_space_kind", "space_id", "kind"),
        {"comment": "运营待办处置状态（轻状态表，撤销即删行）"},
    )

    def __repr__(self) -> str:
        return (
            f"<OpsTodoDisposition(id={self.id}, space_id={self.space_id}, "
            f"kind='{self.kind}', todo_key='{self.todo_key[:32]}', status='{self.status}')>"
        )
