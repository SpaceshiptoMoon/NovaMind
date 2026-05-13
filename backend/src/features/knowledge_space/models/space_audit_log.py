"""
空间审计日志模型

记录知识空间内的所有操作日志
"""

from enum import Enum
from typing import Optional, Dict, Any
from sqlalchemy import Column, BigInteger, Integer, String, Text, DateTime, JSON, ForeignKey

from src.core.database.base import BaseModel


class AuditAction(str, Enum):
    """审计操作类型枚举"""
    # 空间操作
    SPACE_CREATE = "space_create"
    SPACE_UPDATE = "space_update"
    SPACE_DELETE = "space_delete"
    # 成员操作
    MEMBER_INVITE = "member_invite"
    MEMBER_JOIN = "member_join"
    MEMBER_REMOVE = "member_remove"
    MEMBER_ROLE_UPDATE = "member_role_update"
    # 文档操作
    DOCUMENT_UPLOAD = "document_upload"
    DOCUMENT_DELETE = "document_delete"
    DOCUMENT_UPDATE = "document_update"
    # 检索操作
    SEARCH_VECTOR = "search_vector"
    SEARCH_BM25 = "search_bm25"
    SEARCH_HYBRID = "search_hybrid"
    # 知识库操作
    KB_CREATE = "kb_create"
    KB_UPDATE = "kb_update"
    KB_DELETE = "kb_delete"


class SpaceAuditLog(BaseModel):
    """
    空间审计日志模型

    记录知识空间内的所有操作，用于审计和追踪
    """
    __tablename__ = "space_audit_logs"
    __table_args__ = (
        {"comment": "空间审计日志表，记录知识空间内的所有操作日志"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="日志ID")
    space_id = Column(BigInteger, ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, index=True, comment="空间ID")
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True, comment="操作用户ID")

    # 追踪信息
    trace_id = Column(String(64), nullable=True, index=True, comment="追踪ID（关联完整请求链路）")

    # 操作信息（需要索引，保留独立字段）
    action = Column(String(50), nullable=False, index=True, comment="操作类型")

    # P1改进：独立 IP 和 UA 字段
    ip_address = Column(String(45), nullable=True, index=True, comment="操作来源IP")
    user_agent = Column(String(500), nullable=True, comment="客户端User-Agent")

    # 资源信息（合并为 JSON）
    resource = Column(JSON, comment="资源信息（类型、ID等）")

    # 操作详情
    details = Column(JSON, comment="操作详情")
    changes = Column(JSON, comment="变更内容（before/after）")

    # 请求上下文（合并为 JSON）
    context = Column(JSON, comment="请求上下文（IP、UA等）")

    # 时间戳（审计日志只有 created_at，但 BaseModel 自动提供 updated_at）
    # created_at 继承自 BaseModel，使用 now_china() 默认值
    # 注意：updated_at 也由 BaseModel 提供，审计日志场景下自动维护但不影响业务逻辑

    def __repr__(self) -> str:
        return f"<SpaceAuditLog(id={self.id}, space_id={self.space_id}, action='{self.action}')>"

    # ========== Resource 访问方法 ==========

    def get_resource(self) -> dict:
        """获取资源信息"""
        return self.resource or {}

    def get_resource_type(self) -> Optional[str]:
        """获取资源类型"""
        return self.get_resource().get("type")

    def get_resource_id(self) -> Optional[int]:
        """获取资源ID"""
        return self.get_resource().get("id")

    def get_resource_name(self) -> Optional[str]:
        """获取资源名称"""
        return self.get_resource().get("name")

    def set_resource(self, resource_type: str, resource_id: int, resource_name: str = None) -> None:
        """设置资源信息"""
        self.resource = {
            "type": resource_type,
            "id": resource_id
        }
        if resource_name:
            self.resource["name"] = resource_name

    # ========== Context 访问方法 ==========

    def get_context(self) -> dict:
        """获取请求上下文"""
        return self.context or {}

    def get_ip_address(self) -> Optional[str]:
        """获取 IP 地址"""
        return self.ip_address

    def get_user_agent(self) -> Optional[str]:
        """获取用户代理"""
        return self.user_agent

    def get_request_id(self) -> Optional[str]:
        """获取请求ID"""
        return self.get_context().get("request_id")

    def set_context(
        self,
        ip_address: str = None,
        user_agent: str = None,
        request_id: str = None
    ) -> None:
        """设置请求上下文（ip_address 和 user_agent 由独立字段存储，此处仅存 request_id）"""
        if not self.context:
            self.context = {}
        if request_id:
            self.context["request_id"] = request_id

    # ========== Details 访问方法 ==========

    def get_details(self) -> dict:
        """获取操作详情"""
        return self.details or {}

    def set_details(self, details: Dict[str, Any]) -> None:
        """设置操作详情"""
        self.details = details

    def add_detail(self, key: str, value: Any) -> None:
        """添加操作详情"""
        if not self.details:
            self.details = {}
        self.details[key] = value

    # ========== Changes 访问方法 ==========

    def get_changes(self) -> dict:
        """获取变更内容"""
        return self.changes or {}

    def set_changes(self, before: Any = None, after: Any = None) -> None:
        """设置变更内容"""
        self.changes = {
            "before": before,
            "after": after
        }

    @staticmethod
    def create_from_request(
        space_id: int,
        user_id: int,
        action: str,
        request,
        resource_type: str = None,
        resource_id: int = None,
        resource_name: str = None,
        details: dict = None,
        changes: dict = None,
    ) -> "SpaceAuditLog":
        """
        从请求创建审计日志

        Args:
            space_id: 空间ID
            user_id: 用户ID
            action: 操作类型
            request: FastAPI Request 对象
            resource_type: 资源类型
            resource_id: 资源ID
            resource_name: 资源名称
            details: 操作详情
            changes: 变更内容

        Returns:
            SpaceAuditLog 实例
        """
        # 提取 IP 和 UA
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")[:500] if request.headers else None

        log = SpaceAuditLog(
            space_id=space_id,
            user_id=user_id,
            trace_id=getattr(request.state, "trace_id", None),
            action=action,
            details=details,
            changes=changes,
            # P1改进：独立字段
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # 设置资源信息
        if resource_type and resource_id:
            log.set_resource(resource_type, resource_id, resource_name)

        # 设置上下文（保留兼容性）
        log.set_context(
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=getattr(request.state, "request_id", None)
        )

        return log

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "space_id": self.space_id,
            "user_id": self.user_id,
            "trace_id": self.trace_id,
            "action": self.action,
            "resource": self.resource,
            "details": self.details,
            "changes": self.changes,
            "context": self.context,
            # P1改进：独立字段
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
