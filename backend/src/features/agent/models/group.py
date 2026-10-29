"""群聊数据模型

AgentGroup（群定义）/ AgentGroupMember（成员）/ AgentGroupRun（一响编排实例）。
成员私有会话与投递均复用 AgentSession/AgentMessage（extra_config/extra 标记），
本文件只承载纯配置与编排状态，无消息内容。
"""
from novamind.core.database.base import BaseModel
from sqlalchemy import JSON, BigInteger, Column, DateTime, ForeignKey, Index, Integer, String


class AgentGroup(BaseModel):
    """群聊定义"""

    __tablename__ = "agent_groups"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, comment="属主用户ID")
    name = Column(String(100), nullable=False, comment="群名称")
    description = Column(String(500), nullable=True, comment="群描述")
    mode = Column(String(20), nullable=False, default="brainstorm", comment="模式：brainstorm/consult")
    host_agent_id = Column(BigInteger, ForeignKey("agent_definitions.id"), nullable=True, comment="主持人 Agent ID（consult 必填且须为成员）")
    extra_config = Column(JSON, nullable=True, comment="编排参数（rounds_per_turn/max_round_tokens 等）")

    __table_args__ = (
        Index("idx_agent_groups_user", "user_id"),
        {"comment": "群聊定义表"},
    )

    def __repr__(self) -> str:
        return f"<AgentGroup(id={self.id}, name='{self.name}', mode='{self.mode}')>"


class AgentGroupMember(BaseModel):
    """群成员（引用既有 AgentDefinition，不复制其配置）"""

    __tablename__ = "agent_group_members"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    group_id = Column(BigInteger, ForeignKey("agent_groups.id"), nullable=False, comment="群ID")
    agent_id = Column(BigInteger, ForeignKey("agent_definitions.id"), nullable=False, comment="成员 Agent ID")
    role_hint = Column(String(200), nullable=True, comment="角色补充描述（consult 工具描述派生源）")
    speak_order = Column(Integer, nullable=False, default=0, comment="头脑风暴发言顺序")
    joined_at = Column(DateTime, nullable=True, comment="入群时间")

    __table_args__ = (
        Index("idx_agent_group_members_group", "group_id"),
        {"comment": "群聊成员表"},
    )

    def __repr__(self) -> str:
        return f"<AgentGroupMember(id={self.id}, group_id={self.group_id}, agent_id={self.agent_id})>"


class AgentGroupRun(BaseModel):
    """一响编排实例（一次用户消息触发的群执行，隔离与审计单元）"""

    __tablename__ = "agent_group_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    group_id = Column(BigInteger, ForeignKey("agent_groups.id"), nullable=False, comment="群ID")
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, comment="触发用户ID")
    session_id = Column(String(36), ForeignKey("agent_sessions.session_id"), nullable=False, comment="群会话 UUID（时间线所在）")
    status = Column(String(20), nullable=False, default="running", comment="running/done/failed/cancelled")
    mode_snapshot = Column(String(20), nullable=False, comment="触发时的群模式快照")
    orchestration_meta = Column(JSON, nullable=True, comment="审计：发言序列/consult 调用记录")
    error = Column(String(500), nullable=True, comment="失败原因（status=failed 时）")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")

    __table_args__ = (
        # 同群并发护栏查询路径：编排前查 running run 是否存在
        Index("idx_agent_group_runs_group_status", "group_id", "status"),
        {"comment": "群聊编排运行表"},
    )

    def __repr__(self) -> str:
        return f"<AgentGroupRun(id={self.id}, group_id={self.group_id}, status='{self.status}')>"
