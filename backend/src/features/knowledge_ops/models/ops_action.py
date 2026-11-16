"""运营动作登记簿：人（或系统）对知识资产做过什么处置的统一记录。

与事件账本的分工：kb_events 是不可变审计流（含埋点），ops_actions 是
处置动作的权威登记（战果统计与干预回看的数据源）。写入方双写两者，
保持账本审计流兼容。scope/outcome 字段为干预回看（前后对照）预留，
本批次只建列不消费。

action 取值登记（新增在此登记）：
- review_confirmed / gap_converted / todo_ignored（对齐账本既有类型）
- doc_archived / doc_reactivated / suggestion_accepted / suggestion_dismissed
"""
from novamind.core.database.base import BaseModel
from sqlalchemy import JSON, BigInteger, Column, DateTime, ForeignKey, Index, String


class OpsAction(BaseModel):
    """运营动作行：一次处置 = 一行。

    target_kind 取值：document/gap/todo/suggestion/retrieval_config
    （retrieval_config 为检索调优纳入动作登记预留——调参即干预）。
    """

    __tablename__ = "ops_actions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    space_id = Column(BigInteger, nullable=False, index=True, comment="空间ID")
    actor_id = Column(BigInteger, nullable=False, index=True, comment="处置人用户ID")
    action = Column(String(64), nullable=False, comment="动作类型（模块注释维护枚举）")
    target_kind = Column(String(32), nullable=False, comment="目标类别：document/gap/todo/suggestion/retrieval_config")
    target_id = Column(String(64), nullable=False, comment="目标标识（文档ID/聚簇键/待办键等）")
    parent_action_id = Column(
        BigInteger, ForeignKey("ops_actions.id", ondelete="SET NULL"), nullable=True, comment="复检等二次处置的前序动作"
    )

    scope = Column(JSON, nullable=True, comment="干预面：{query_hashes: [...], size: N}（干预回看用）")
    context_snapshot = Column(JSON, nullable=True, comment="动作时上下文快照（当时的指标/触发摘要）")

    outcome = Column(String(24), nullable=False, default="completed", comment="评估结论：completed（回看填充 effective 等）")
    outcome_detail = Column(JSON, nullable=True, comment="最近一次评估依据（数字/阈值/窗口）")
    evaluated_at = Column(DateTime, nullable=True, comment="最近一次评估时间")

    __table_args__ = (
        Index("idx_ops_actions_space_action_created", "space_id", "action", "created_at"),
        {"comment": "运营动作登记簿（统一处置入口，干预回看数据源）"},
    )

    def __repr__(self) -> str:
        return (
            f"<OpsAction(id={self.id}, action='{self.action}', space_id={self.space_id}, "
            f"target='{self.target_kind}:{str(self.target_id)[:24]}', outcome='{self.outcome}')>"
        )
