"""知识运营事件模型：跨会话/用户行为的运营信号账本。

事件类型（新增在此登记）：
- query_reformulate：会话内提问改写（O1）
- citation_click：用户点击回答引用（O2）
- query：检索发生（InstrumentedSearchService 总线级埋点；含 results_count/
  max_score 载荷，零命中/低分是归因流水线核心信号）
- attribution：归因写回（A1）

系统内部检索重放（kb-ops 归因 worker、evaluation 重放）不产生 query 事件
——它们直接用 SearchService，只有用户触发的检索走 InstrumentedSearchService。
"""
from novamind.core.database.base import BaseModel
from sqlalchemy import JSON, BigInteger, Column, Index, String


class KbEvent(BaseModel):
    """运营事件：只追加不修改的账本行。

    设计要点：
    - extra JSON 承载事件私有载荷（如 query_reformulate 的相似度分数、被改写事件 id），
      避免 event_type 膨胀后列数失控；
    - query_text 默认经 redact 脱敏后落库（EventRecorder 保证，本模型不做二次处理）。
    """

    __tablename__ = "kb_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(String(32), nullable=False, comment="事件类型：query_reformulate/citation_click/attribution/...")
    user_id = Column(BigInteger, nullable=False, index=True, comment="触发用户ID")
    session_id = Column(String(36), nullable=True, index=True, comment="关联会话ID（跨会话事件可空）")
    space_id = Column(BigInteger, nullable=True, index=True, comment="关联空间ID（权限域过滤必带）")
    kb_id = Column(BigInteger, nullable=True, comment="关联知识库ID（可空）")

    # 查询文本（脱敏后）。citation_click 等无文本事件为 NULL，节省存储。
    query_text = Column(String(512), nullable=True, comment="脱敏后的查询文本（可空）")

    # 事件私有载荷：{reformulates_event_id, similarity, ...}
    extra = Column(JSON, nullable=True, comment="事件载荷（事件类型私有结构）")

    __table_args__ = (
        Index("idx_kb_events_space_type_created", "space_id", "event_type", "created_at"),
        Index("idx_kb_events_session_created", "session_id", "created_at"),
        {"comment": "知识运营事件账本（只追加）：用户行为信号/归因结果"},
    )

    def __repr__(self) -> str:
        return (
            f"<KbEvent(id={self.id}, event_type='{self.event_type}', "
            f"user_id={self.user_id}, session_id='{self.session_id}')>"
        )
