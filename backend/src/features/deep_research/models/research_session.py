"""
研究会话模型

存储深度研究的会话信息、研究任务和结果
"""

from typing import Optional
from sqlalchemy import Column, BigInteger, SmallInteger, String, Text, DateTime, JSON, Index, ForeignKey
from sqlalchemy.orm.attributes import flag_modified
from enum import Enum as PyEnum, IntEnum
import uuid

from novamind.core.database.base import BaseModel
from novamind.shared.utils.time_utils import now_china


class ResearchStatus(IntEnum):
    """研究状态枚举（整数类型）"""
    PENDING = 0      # 待开始
    RUNNING = 1      # 运行中
    COMPLETED = 2    # 已完成
    FAILED = 3       # 失败
    CANCELLED = 4    # 已取消



class ResearchMode(str, PyEnum):
    """研究模式枚举"""
    QUICK = "quick"           # 快速模式
    STANDARD = "standard"      # 标准模式
    DEEP = "deep"              # 深度模式


class SearchSource(str, PyEnum):
    """检索来源枚举"""
    INTERNAL = "internal"      # 内部知识库
    EXTERNAL = "external"      # 外部网络搜索
    HYBRID = "hybrid"          # 混合检索


class ExternalSearchProvider(str, PyEnum):
    """外部搜索提供商枚举"""
    TAVILY = "tavily"          # Tavily
    SERPAPI = "serpapi"        # SerpAPI
    DUCKDUCKGO = "duckduckgo"  # DuckDuckGo


class ResearchSession(BaseModel):
    """
    深度研究会话模型

    存储研究任务、策略选择和最终报告
    """
    __tablename__ = "research_sessions"

    # 基础信息
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="研究会话ID")
    space_id = Column(
        BigInteger,
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="知识空间ID",
    )
    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="用户ID",
    )
    session_id = Column(String(64), nullable=False, unique=True, index=True, comment="会话唯一标识")

    # 研究主题
    query = Column(Text, nullable=False, comment="研究问题")

    # 配置（合并为 JSON）
    config = Column(JSON, comment="研究配置")

    # 研究模式（字符串枚举，配置类型）
    mode = Column(String(20), default="standard", nullable=False, comment="研究模式: quick/standard/deep")

    # 检索来源（字符串枚举，配置类型）
    search_source = Column(String(20), default="hybrid", nullable=False, comment="检索来源: internal/external/hybrid")

    # 外部搜索提供商（可选）
    external_provider = Column(String(50), nullable=True, comment="外部搜索提供商")

    # 状态（整数枚举）
    status = Column(
        SmallInteger,
        default=ResearchStatus.PENDING,
        nullable=False,
        index=True,
        comment="状态: 0-待开始, 1-运行中, 2-已完成, 3-失败, 4-已取消"
    )

    # 状态详情
    status_info = Column(JSON, comment="状态详情（错误、时间等）")

    # 研究计划
    plan = Column(JSON, comment="研究计划")

    # 结果
    result = Column(JSON, comment="研究结果")
    stats = Column(JSON, comment="统计信息")

    # 时间字段（独立字段便于统计耗时）
    started_at = Column(DateTime, nullable=True, index=True, comment="研究开始时间")
    completed_at = Column(DateTime, nullable=True, index=True, comment="研究完成时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")

    # created_at 和 updated_at 由 BaseModel 基类提供

    # 索引
    __table_args__ = (
        Index("idx_space_status", "space_id", "status"),
        Index("idx_user_status", "user_id", "status"),
        {"comment": "深度研究会话表，存储研究任务、策略配置和研究结果"},
    )

    def __repr__(self) -> str:
        return f"<ResearchSession(id={self.id}, query='{self.query[:30]}...', status={self.status})>"

    @staticmethod
    def generate_session_id() -> str:
        """生成会话ID（32 字符 hex，无连字符）"""
        return uuid.uuid4().hex

    # ========== Config 访问方法 ==========

    def get_config(self) -> dict:
        """获取研究配置"""
        return self.config or {}

    def get_search_depth(self) -> int:
        """获取搜索深度"""
        return self.get_config().get("search_depth", 3)

    # ========== Status Info 访问方法 ==========

    def get_status_info(self) -> dict:
        """获取状态详情"""
        return self.status_info or {}

    def get_error_message(self) -> Optional[str]:
        """获取错误信息"""
        return self.get_status_info().get("error_message")

    def set_started(self) -> None:
        """标记为开始研究"""
        self.status = ResearchStatus.RUNNING
        if not self.status_info:
            self.status_info = {}
        self.status_info["started_at"] = now_china().isoformat()
        flag_modified(self, "status_info")

    def set_error(self, error_message: str) -> None:
        """设置错误信息"""
        if not self.status_info:
            self.status_info = {}
        self.status_info["error_message"] = error_message
        self.status_info["completed_at"] = now_china().isoformat()
        flag_modified(self, "status_info")

    def set_cancelled(self, reason: str = None) -> None:
        """设置取消状态"""
        if not self.status_info:
            self.status_info = {}
        self.status_info["cancelled_at"] = now_china().isoformat()
        if reason:
            self.status_info["cancel_reason"] = reason
        flag_modified(self, "status_info")

    # ========== Result 访问方法 ==========

    def get_result(self) -> dict:
        """获取研究结果"""
        return self.result or {}

    def set_result(
        self,
        answer: str = None,
        sources: list = None,
        reasoning_steps: list = None,
        confidence: float = None
    ) -> None:
        """设置研究结果"""
        if not self.result:
            self.result = {}

        if answer is not None:
            self.result["answer"] = answer
        if sources is not None:
            self.result["sources"] = sources
        if reasoning_steps is not None:
            self.result["reasoning_steps"] = reasoning_steps
        if confidence is not None:
            self.result["confidence"] = confidence
        flag_modified(self, "result")

    # ========== Stats 访问方法 ==========

    # ========== 状态变更方法 ==========

    def is_running(self) -> bool:
        """检查是否运行中"""
        return self.status == ResearchStatus.RUNNING

    def is_failed(self) -> bool:
        """检查是否失败"""
        return self.status == ResearchStatus.FAILED

    def mark_started(self) -> None:
        """标记为开始研究"""
        self.status = ResearchStatus.RUNNING
        self.started_at = now_china()
        self.set_started()

    def mark_completed(self, answer: str, sources: list = None, stats: dict = None) -> None:
        """标记为研究完成"""
        self.status = ResearchStatus.COMPLETED
        self.completed_at = now_china()
        self.set_result(answer=answer, sources=sources)
        if stats:
            self.stats = stats
            flag_modified(self, "stats")
        if not self.status_info:
            self.status_info = {}
        self.status_info["completed_at"] = now_china().isoformat()
        flag_modified(self, "status_info")

    def mark_failed(self, error_message: str) -> None:
        """标记为研究失败"""
        self.status = ResearchStatus.FAILED
        self.completed_at = now_china()
        self.set_error(error_message)

    def mark_cancelled(self, reason: str = None) -> None:
        """标记为取消研究"""
        self.status = ResearchStatus.CANCELLED
        self.completed_at = now_china()
        self.set_cancelled(reason)
