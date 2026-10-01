"""文档模型：上传文档的元数据与 MinIO 存储信息（处理状态已迁至 DocumentTask）。"""
from enum import IntEnum

from novamind.core.database.base import BaseModel
from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)


# 保留此枚举用于过渡期兼容 — 旧代码仍可导入，但 Document 模型本身不再使用
# 新代码应使用 TaskStatus（models/document_task.py）
class DocumentStatus(IntEnum):
    """文档处理状态枚举（已废弃，保留用于向后兼容）"""
    UPLOADED = 0     # 已上传 → 请用 TaskStatus.PENDING
    PROCESSING = 1   # 处理中 → 请用 TaskStatus.PROCESSING
    COMPLETED = 2    # 已完成 → 请用 TaskStatus.COMPLETED
    FAILED = 3       # 处理失败 → 请用 TaskStatus.FAILED
    DELETED = 4      # 已删除 → Document.deleted_at


class DocumentLifecycleStatus:
    """文档生命周期状态常量（kb-ops B1）。

    状态机：draft → active → superseded → archived，仅 archived → active 允许回退。
    检索默认只召回 active（及无该字段的存量数据——排除式过滤语义）。
    """

    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"

    # 合法转换表（单向为主，archived → active 为唯一回退）
    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        DRAFT: {ACTIVE},
        ACTIVE: {SUPERSEDED, ARCHIVED},
        SUPERSEDED: {ARCHIVED, ACTIVE},  # superseded → active：误替换恢复
        ARCHIVED: {ACTIVE},              # 归档误操作恢复
    }

    # 参与检索的状态白名单（排除式过滤的补集面）
    RETIREMENT_STATES = {SUPERSEDED, ARCHIVED}


class Document(BaseModel):
    """
    文档模型 — 纯文件元数据

    仅存储文件本身的信息。处理状态、重试、错误等全部由 DocumentTaskItem 管理。
    """
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="文档ID")
    space_id = Column(BigInteger, ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属空间ID")
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属知识库ID")
    uploader_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True, comment="上传者用户ID")

    # 文件核心信息
    filename = Column(String(255), nullable=False, comment="存储文件名")
    file_type = Column(String(50), nullable=False, comment="文件类型（pdf/docx/txt/md）")
    file_size = Column(BigInteger, nullable=False, comment="文件大小（字节）")
    file_hash = Column(String(64), nullable=False, index=True, comment="文件哈希值（去重，按 知识库+上传者 隔离）")

    # 存储信息（MinIO 路径 + parsed_text_object）
    storage = Column(JSON, nullable=False, default=dict, comment="存储信息（MinIO）")

    deleted_at = Column(DateTime, nullable=True, index=True, comment="软删除时间")

    # ========== 生命周期治理（kb-ops B1：Glean 式新鲜度四要素） ==========
    # 存量表由 SCHEMA_MIGRATIONS 幂等补列；owner 回填 uploader_id 见迁移注释。

    lifecycle_status = Column(
        String(16),
        nullable=False,
        default=DocumentLifecycleStatus.ACTIVE,
        comment="生命周期：draft/active/superseded/archived；检索默认只召回 active",
    )
    owner_id = Column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=True,
        comment="内容责任人（新上传默认 uploader_id；存量由迁移回填）",
    )
    effective_date = Column(DateTime, nullable=True, comment="生效时间（时效性过滤/展示用）")
    review_cycle_days = Column(Integer, nullable=True, comment="复审周期（天）；KB 级默认值可被文档覆盖")
    next_review_at = Column(DateTime, nullable=True, index=True, comment="下次复审时间（到期提醒扫描字段）")
    superseded_by_doc_id = Column(
        BigInteger,
        nullable=True,
        comment="被哪个新版文档替代（版本链锚点，superseded 态必填）",
    )

    # 索引和约束
    __table_args__ = (
        # 去重范围：同知识库 + 同上传者 + 同内容哈希。不同成员可各自上传同一文件。
        # 存量库由 startup 期 CONSTRAINT_MIGRATIONS 把旧 uq_kb_file_hash 换成此约束。
        UniqueConstraint("kb_id", "uploader_id", "file_hash", name="uq_kb_uploader_file_hash"),
        Index("idx_space_created", "space_id", "created_at"),
        Index("idx_space_lifecycle", "space_id", "lifecycle_status"),
        {"comment": "文档表，存储文件元数据；处理状态见 document_task_items 表"},
    )

    # 关联关系

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, filename='{self.filename}')>"

    # ========== 存储信息 ==========

    def get_storage_info(self) -> dict:
        """读取存储 JSON 段（MinIO 桶/对象键/媒体产物锚点）。"""
        return self.storage or {}

    def get_minio_bucket(self) -> str | None:
        """获取 MinIO 桶名"""
        return self.get_storage_info().get("minio_bucket")

    def set_minio_info(self, bucket: str, object_name: str, etag: str | None = None) -> None:
        """设置 MinIO 信息。

        Args:
            bucket: MinIO 桶名。
            object_name: 文档对象键。
            etag: 可选上传返回的 ETag，缺省写 None。

        Returns:
            无返回；合并进 storage JSON 列并保留既有键。
        """
        self.storage = {
            **(self.storage or {}),
            "minio_bucket": bucket,
            "minio_object_name": object_name,
            "minio_etag": etag,
        }

    # ========== 软删除 ==========

    def undelete(self, uploader_id: int, filename: str) -> None:
        """复活已软删除的文档（同文件重新上传）

        仅清除软删除标记并更新上传者/文件名。处理任务由调用方另行创建。
        """
        self.deleted_at = None
        self.uploader_id = uploader_id
        self.filename = filename
