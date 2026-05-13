"""
知识库模型

核心新增表：一个空间下可以有多个知识库，每个知识库有独立的切分/解析/向量化/检索配置

Embedding 模型配置存储在 config.embedding 中：
- embedding_model: 绑定的模型名称
- embedding_config_version: 配置版本号
- vector_index_status: 向量索引状态
"""
from typing import Optional
from enum import IntEnum
from sqlalchemy import Column, BigInteger, SmallInteger, String, Text, Boolean, JSON, DateTime, ForeignKey, Index, UniqueConstraint, Integer
from sqlalchemy.orm import relationship
from src.core.database.base import BaseModel
from src.shared.utils.time_utils import now_china


class KnowledgeBaseStatus(IntEnum):
    """知识库状态枚举（整数类型）"""
    DELETED = 0   # 已删除
    ACTIVE = 1    # 活跃
    ARCHIVED = 2  # 已归档


class KnowledgeBase(BaseModel):
    """
    知识库模型

    存储知识库的配置和统计信息

    Embedding 模型配置存储在 config.embedding 中：
    - embedding_model: 模型名称
    - embedding_config_version: 版本号
    - vector_index_status: 索引状态
    """
    __tablename__ = "knowledge_bases"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    space_id = Column(BigInteger, ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, comment="所属空间")
    name = Column(String(100), nullable=False, comment="知识库名称")
    creator_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, comment="创建者")

    # 所有配置统一放入 JSON（便于后期扩展新策略）
    config = Column(JSON, nullable=False, comment="知识库配置")

    # 存储配置
    storage = Column(JSON, comment="存储配置（ES索引、MinIO路径）")

    # 统计信息（异步更新）
    stats = Column(JSON, comment="统计信息")

    # 状态（整数枚举）
    status = Column(
        SmallInteger,
        default=KnowledgeBaseStatus.ACTIVE,
        nullable=False,
        index=True,
        comment="状态: 0-已删除, 1-活跃, 2-已归档"
    )

    # 软删除
    deleted_at = Column(DateTime, nullable=True, index=True, comment="软删除时间")

    # 时间戳
    created_at = Column(
        DateTime,
        default=lambda: now_china(),
        nullable=False,
        comment="创建时间"
    )
    updated_at = Column(
        DateTime,
        default=lambda: now_china(),
        onupdate=lambda: now_china(),
        nullable=False,
        comment="更新时间"
    )

    # 关联关系（双向：KnowledgeBase.documents <-> Document.knowledge_base）
    documents = relationship("Document", back_populates="knowledge_base", lazy="noload", passive_deletes=True)

    # 索引和约束
    __table_args__ = (
        # 空间内知识库名称唯一
        UniqueConstraint("space_id", "name", name="uq_space_kb_name"),
        {"comment": "知识库表，存储知识库的切分/解析/向量化/检索配置和统计信息"},
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase(id={self.id}, name='{self.name}', status={self.status})>"

    # ========== 配置访问方法 ==========

    def get_config(self) -> dict:
        """获取完整配置"""
        return self.config or {}

    def get_splitting_config(self) -> dict:
        """获取切分配置"""
        return (self.config or {}).get("splitting", {})

    def get_parsing_config(self) -> dict:
        """获取解析配置"""
        return (self.config or {}).get("parsing", {})

    def get_retrieval_config(self) -> dict:
        """获取检索配置"""
        return (self.config or {}).get("retrieval", {})

    def get_question_generation_config(self) -> dict:
        """获取假设问题生成配置"""
        return (self.config or {}).get("question_generation", {})

    def is_question_generation_enabled(self) -> bool:
        """检查知识库是否启用了问题生成"""
        qg_config = self.get_question_generation_config()
        return qg_config.get("enabled", False)

    def get_available_search_modes(self) -> list:
        """获取可用的检索模式列表"""
        # 仅内容模式始终可用
        content_modes = ["content_bm25", "content_vector", "content_hybrid"]

        if self.is_question_generation_enabled():
            # 启用问题生成，所有模式可用
            return [
                *content_modes,
                "question_bm25", "question_vector", "question_hybrid",
                "all_bm25", "all_vector", "all_hybrid"
            ]
        else:
            # 未启用问题生成，仅内容模式可用
            return content_modes

    def enable_question_generation(self, max_questions: int = 5) -> None:
        """启用问题生成功能"""
        self.config = {
            **(self.config or {}),
            "question_generation": {
                "enabled": True,
                "max_questions_per_chunk": max_questions,
            },
        }

    def get_description(self) -> Optional[str]:
        """获取描述"""
        return (self.config or {}).get("description")

    def get_es_index_name(self) -> Optional[str]:
        """获取 ES 索引名"""
        return (self.storage or {}).get("es_index_name") if self.storage else None

    def get_minio_prefix(self) -> Optional[str]:
        """获取 MinIO 路径前缀"""
        return (self.storage or {}).get("minio_prefix") if self.storage else None

    def is_active(self) -> bool:
        """检查知识库是否可用"""
        return self.status == KnowledgeBaseStatus.ACTIVE and self.deleted_at is None

    def is_deleted(self) -> bool:
        """检查知识库是否已删除"""
        return self.status == KnowledgeBaseStatus.DELETED or self.deleted_at is not None

    def is_archived(self) -> bool:
        """检查知识库是否已归档"""
        return self.status == KnowledgeBaseStatus.ARCHIVED

    # ========== 软删除方法 ==========

    def soft_delete(self) -> None:
        """软删除知识库"""
        self.status = KnowledgeBaseStatus.DELETED
        self.deleted_at = now_china()

    def restore(self) -> None:
        """恢复已删除的知识库"""
        self.status = KnowledgeBaseStatus.ACTIVE
        self.deleted_at = None

    def archive(self) -> None:
        """归档知识库"""
        self.status = KnowledgeBaseStatus.ARCHIVED


# ========== 默认配置模板 ==========

DEFAULT_STORAGE = {
    "es_index_name": None,  # 自动生成
    "minio_prefix": None,  # 自动生成
}

