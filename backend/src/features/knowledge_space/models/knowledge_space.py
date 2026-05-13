"""
知识空间模型

存储知识空间的基本信息和配置
"""
from typing import Optional
from enum import IntEnum
from sqlalchemy import Column, BigInteger, Integer, SmallInteger, String, Text, DateTime, JSON, ForeignKey, Index, UniqueConstraint

from src.core.database.base import BaseModel
from src.shared.utils.time_utils import now_china


class SpaceVisibility(IntEnum):
    """空间可见性枚举（整数类型）"""
    PRIVATE = 0  # 私有（仅成员可见）
    TEAM = 1     # 团队（内部可见）
    PUBLIC = 2   # 公开（所有人可见）


class SpaceStatus(IntEnum):
    """空间状态枚举（整数类型）"""
    ACTIVE = 1    # 活跃
    ARCHIVED = 2  # 已归档
    DELETED = 3   # 已删除


class KnowledgeSpace(BaseModel):
    """
    知识空间模型

    存储知识空间的元数据和配置信息
    """
    __tablename__ = "knowledge_spaces"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="空间ID")
    name = Column(String(100), nullable=False, comment="空间名称")
    owner_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True, comment="创建者用户ID")

    # 访问控制（整数枚举）
    visibility = Column(
        SmallInteger,
        default=SpaceVisibility.PRIVATE,
        nullable=False,
        index=True,
        comment="可见性: 0-私有, 1-团队, 2-公开"
    )

    # 统计信息
    storage_used_mb = Column(Integer, default=0, nullable=False, comment="已使用存储空间（MB）")

    # 所有配置统一放入 JSON
    config = Column(JSON, comment="空间配置（描述、存储、UI等）")

    # 状态（整数枚举）
    status = Column(
        SmallInteger,
        default=SpaceStatus.ACTIVE,
        nullable=False,
        index=True,
        comment="状态: 1-活跃, 2-归档, 3-删除"
    )

    # 软删除
    deleted_at = Column(DateTime, nullable=True, comment="删除时间（软删除）")

    # created_at 和 updated_at 由 BaseModel 基类提供

    # 索引和约束
    __table_args__ = (
        Index("idx_owner_status", "owner_id", "status"),
        {"comment": "知识空间表，存储知识空间的基本信息、配置和状态"},
    )

    def __repr__(self) -> str:
        return f"<KnowledgeSpace(id={self.id}, name='{self.name}', status={self.status})>"

    # ========== 配置访问方法 ==========

    def get_config(self) -> dict:
        """获取完整配置"""
        return self.config or {}

    def get_description(self) -> Optional[str]:
        """获取描述"""
        return self.get_config().get("description", "")

    def get_tags(self) -> list:
        """获取标签"""
        return self.get_config().get("tags", [])

    def get_ui_config(self) -> dict:
        """获取 UI 配置"""
        return self.get_config().get("ui", {})

    def get_storage_config(self) -> dict:
        """获取存储配置"""
        return self.get_config().get("storage", {})

    def get_minio_bucket(self) -> Optional[str]:
        """获取 MinIO 桶名"""
        return self.get_storage_config().get("minio_bucket")

    def get_minio_prefix(self) -> Optional[str]:
        """获取 MinIO 路径前缀"""
        return self.get_storage_config().get("minio_prefix")

    # ========== Embedding 配置 ==========

    @property
    def embedding_config(self) -> Optional[dict]:
        """获取空间级别的 Embedding 配置"""
        return self.get_config().get("embedding")

    @property
    def embedding_model(self) -> Optional[str]:
        """获取空间级别的 Embedding 模型"""
        emb = self.embedding_config
        return emb.get("model") if emb else None

    @property
    def embedding_dimension(self) -> Optional[int]:
        """获取空间级别的 Embedding 维度"""
        emb = self.embedding_config
        return emb.get("dimension") if emb else None

    def get_defaults_config(self) -> dict:
        """获取默认配置"""
        return self.get_config().get("defaults", {})

    def get_limits_config(self) -> dict:
        """获取限制配置"""
        return self.get_config().get("limits", {})

    def get_max_documents(self) -> int:
        """获取最大文档数"""
        return self.get_limits_config().get("max_documents", 1000)

    def get_max_storage_mb(self) -> int:
        """获取最大存储空间"""
        return self.get_limits_config().get("max_storage_mb", 10240)

    def get_default_splitting_config(self) -> dict:
        """获取默认切分配置"""
        return self.get_defaults_config().get("splitting", {
            "strategy": "recursive",
            "chunk_size": 500,
            "chunk_overlap": 50
        })

    # ========== 状态检查方法 ==========

    def is_deleted(self) -> bool:
        """检查空间是否已被删除"""
        return self.status == SpaceStatus.DELETED or self.deleted_at is not None

    def is_active(self) -> bool:
        """检查空间是否可用"""
        return self.status == SpaceStatus.ACTIVE and self.deleted_at is None

    def is_archived(self) -> bool:
        """检查空间是否已归档"""
        return self.status == SpaceStatus.ARCHIVED

    def is_private(self) -> bool:
        """检查是否是私有空间"""
        return self.visibility == SpaceVisibility.PRIVATE

    def is_team_visible(self) -> bool:
        """检查是否对团队可见"""
        return self.visibility == SpaceVisibility.TEAM

    def is_public(self) -> bool:
        """检查是否是公开空间"""
        return self.visibility == SpaceVisibility.PUBLIC

    # ========== 状态变更方法 ==========

    def archive(self) -> None:
        """归档空间"""
        self.status = SpaceStatus.ARCHIVED

    def soft_delete(self) -> None:
        """软删除空间"""
        self.status = SpaceStatus.DELETED
        self.deleted_at = now_china()

    def restore(self) -> None:
        """恢复空间"""
        self.status = SpaceStatus.ACTIVE
        self.deleted_at = None
