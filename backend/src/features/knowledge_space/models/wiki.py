"""
Wiki 页面模型

文档解析完成后，由 LLM 管道把知识库文档整理成互相链接、带引用溯源的
Markdown wiki 页面（实体页/概念页/摘要页）。移植自 WeKnora 的 wiki 机制，
按 NovaMind 的 MySQL + 特征分层做了适配：

- 软删唯一约束：WeKnora 用 Postgres partial unique index（WHERE deleted_at IS NULL），
  MySQL 不支持，改用 deleted_flag（0=存活，删除时写时间戳）纳入唯一键。
- 目录树：MVP 不建 wiki_folders 表，页面携带扁平 category_path（JSON 数组）。
- 版本快照：当前版本只存 wiki_pages；页面被覆盖前，旧版本整份快照进
  wiki_page_revisions，(page_id, version) 唯一约束 + 冲突跳过保证写路径幂等。
"""
import uuid
from enum import IntEnum
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, JSON, SmallInteger, String, Text, UniqueConstraint

from novamind.core.database.base import BaseModel
from novamind.shared.utils.time_utils import now_china


class WikiPageType:
    """页面类型常量"""

    SUMMARY = "summary"    # 单篇源文档的摘要页
    ENTITY = "entity"      # 实体页（人/组织/产品/技术等）
    CONCEPT = "concept"    # 概念/主题页
    SYNTHESIS = "synthesis"    # 综合分析页（仅 Agent 经工具创建，管道不自动生成）
    COMPARISON = "comparison"  # 对比页（仅 Agent 经工具创建）

    @classmethod
    def all_types(cls) -> tuple:
        return (cls.SUMMARY, cls.ENTITY, cls.CONCEPT, cls.SYNTHESIS, cls.COMPARISON)

    @classmethod
    def ingest_types(cls) -> tuple:
        """管道自动生成的类型"""
        return (cls.SUMMARY, cls.ENTITY, cls.CONCEPT)


class WikiPageStatus:
    """页面状态常量"""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class WikiEditSource:
    """版本作者类型常量"""

    PIPELINE = "pipeline"  # wiki 生成管道写入（历史遗留空串也按此处理）
    USER = "user"          # 人工在编辑器/API 写入
    AGENT = "agent"        # Agent 经工具写入
    REVERT = "revert"      # 回滚产生的版本


class WikiIngestStatus(IntEnum):
    """wiki 生成任务状态"""

    PENDING = 0
    RUNNING = 1
    DONE = 2
    FAILED = 3


# 版本快照两级保留：软上限只清理机器写的快照，硬上限一律裁剪
WIKI_MAX_REVISIONS_PER_PAGE = 50
WIKI_MAX_REVISIONS_HARD_CAP = 200
# 视为可裁剪的快照来源（历史遗留空串同样可裁剪）
WIKI_PRUNABLE_EDIT_SOURCES = ("", WikiEditSource.PIPELINE)


def new_wiki_id() -> str:
    """生成 wiki 页面/快照的 UUID 主键"""
    return str(uuid.uuid4())


class WikiPage(BaseModel):
    """Wiki 页面（当前版本）"""
    __tablename__ = "wiki_pages"

    id = Column(String(36), primary_key=True, default=new_wiki_id, comment="页面 UUID")
    space_id = Column(BigInteger, ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属空间ID")
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属知识库ID")

    # KB 内唯一标识，格式 "<type>/<name>"，如 entity/acme-corp、summary/<document_id>
    slug = Column(String(255), nullable=False, comment="页面 slug（KB 内唯一）")
    title = Column(String(512), nullable=False, comment="页面标题")
    page_type = Column(String(32), nullable=False, default=WikiPageType.ENTITY, index=True, comment="页面类型")
    status = Column(String(32), nullable=False, default=WikiPageStatus.PUBLISHED, comment="页面状态")
    content = Column(Text, nullable=False, default="", comment="Markdown 正文")
    summary = Column(Text, nullable=False, default="", comment="一句话摘要（索引列表展示）")
    aliases = Column(JSON, nullable=False, default=list, comment="别名列表")
    category_path = Column(JSON, nullable=False, default=list, comment="扁平目录路径，如 ['人物','技术专家']")

    # 来源引用：文档级 "<document_id>|<filename>" 列表；chunk 级证据 "<document_id>_<idx>" 列表
    source_refs = Column(JSON, nullable=False, default=list, comment="来源文档引用")
    chunk_refs = Column(JSON, nullable=False, default=list, comment="分块级证据引用")

    # 链接图（slug 列表），finalize 阶段双向对齐
    in_links = Column(JSON, nullable=False, default=list, comment="反向链接 slug 列表")
    out_links = Column(JSON, nullable=False, default=list, comment="正向链接 slug 列表")

    # 仅用户可见字段变更才递增；链接维护等簿记写不动它
    version = Column(BigInteger, nullable=False, default=1, comment="版本号")
    last_edit_source = Column(String(16), nullable=False, default="", comment="当前版本作者：pipeline/user/agent/revert")
    last_editor_id = Column(BigInteger, nullable=True, comment="操作者用户 ID（管道写入为空）")

    # Django 式软删：0=存活；删除时写 China 时间戳（微秒），存活行冲突、软删行互不冲突
    deleted_flag = Column(BigInteger, nullable=False, default=0, comment="软删标记：0=存活，删除时写时间戳")
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")

    __table_args__ = (
        UniqueConstraint("kb_id", "slug", "deleted_flag", name="uq_wiki_kb_slug_alive"),
        Index("idx_wiki_kb_type_status", "kb_id", "page_type", "status"),
        Index("idx_wiki_kb_deleted", "kb_id", "deleted_flag"),
        {"comment": "Wiki 页面表（当前版本）"},
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_flag != 0

    def source_document_ids(self) -> list:
        """从 source_refs 提取文档 ID 列表（"docid|filename" → docid）"""
        ids = []
        for ref in self.source_refs or []:
            ref = str(ref).strip()
            if not ref:
                continue
            doc_id = ref.split("|", 1)[0].strip()
            if doc_id:
                ids.append(doc_id)
        return ids

    def soft_delete(self) -> None:
        """软删除：deleted_flag 写时间戳以让出 (kb_id, slug) 唯一占位"""
        if self.deleted_flag == 0:
            self.deleted_flag = int(now_china().timestamp() * 1_000_000)
            self.deleted_at = now_china()

    def content_signature_changed(self, *, title: str, content: str, summary: str,
                                   page_type: str, status: str) -> bool:
        """判断用户可见字段是否变化（决定 version 是否递增）"""
        return (
            self.title != title
            or self.content != content
            or self.summary != summary
            or self.page_type != page_type
            or self.status != status
        )


class WikiPageRevision(BaseModel):
    """Wiki 页面历史快照（不可变）

    页面被覆盖前，旧版本先整份写入本表；(page_id, version) 唯一约束配合
    写入时容忍冲突，使「先快照再更新」在任务重试下保持幂等。
    """
    __tablename__ = "wiki_page_revisions"

    id = Column(String(36), primary_key=True, default=new_wiki_id, comment="快照 UUID")
    page_id = Column(String(36), ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=False, comment="页面 UUID")
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属知识库ID")
    version = Column(BigInteger, nullable=False, comment="被快照的版本号")
    slug = Column(String(255), nullable=False, comment="页面 slug（冗余，便于按 slug 查历史）")
    title = Column(String(512), nullable=False, comment="该版本标题")
    page_type = Column(String(32), nullable=False, comment="该版本类型")
    status = Column(String(32), nullable=False, comment="该版本状态")
    content = Column(Text, nullable=False, default="", comment="该版本 Markdown 正文")
    summary = Column(Text, nullable=False, default="", comment="该版本摘要")
    aliases = Column(JSON, nullable=False, default=list, comment="该版本别名")
    edit_source = Column(String(16), nullable=False, default="", comment="该版本作者：pipeline/user/agent/revert")
    editor_id = Column(BigInteger, nullable=True, comment="该版本操作者用户 ID")
    edited_at = Column(DateTime, nullable=False, default=now_china, comment="该版本撰写时间")

    __table_args__ = (
        UniqueConstraint("page_id", "version", name="uq_wiki_revision_page_version"),
        Index("idx_wiki_revision_kb_slug", "kb_id", "slug"),
        {"comment": "Wiki 页面历史快照"},
    )


class WikiIngestRecord(BaseModel):
    """Wiki 生成任务履历（轻量）

    每个文档触发的 wiki 生成写一行，供前端轮询「生成中」状态与排查失败。
    step_progress 仿 DocumentTask：每阶段 start/finish 即 commit，崩溃可见。
    """
    __tablename__ = "wiki_ingest_records"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="履历 ID")
    space_id = Column(BigInteger, ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属空间ID")
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属知识库ID")
    document_id = Column(BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True, comment="触发文档ID")
    job_id = Column(String(64), nullable=True, comment="arq job ID")
    status = Column(SmallInteger, default=WikiIngestStatus.PENDING, nullable=False, index=True, comment="任务状态")
    step_progress = Column(JSON, nullable=True, comment="阶段进度")
    pages_created = Column(SmallInteger, nullable=False, default=0, comment="新建页面数")
    pages_updated = Column(SmallInteger, nullable=False, default=0, comment="更新页面数")
    error_message = Column(Text, nullable=True, comment="失败原因")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")

    __table_args__ = (
        Index("idx_wiki_ingest_kb_status", "kb_id", "status"),
        {"comment": "Wiki 生成任务履历"},
    )

    def mark_running(self) -> None:
        self.status = WikiIngestStatus.RUNNING
        self.started_at = now_china()

    def mark_done(self, pages_created: int, pages_updated: int) -> None:
        self.status = WikiIngestStatus.DONE
        self.pages_created = pages_created
        self.pages_updated = pages_updated
        self.completed_at = now_china()
        self.error_message = None

    def mark_failed(self, error_message: str) -> None:
        self.status = WikiIngestStatus.FAILED
        self.completed_at = now_china()
        self.error_message = error_message

    def start_step(self, step_name: str) -> None:
        """记录阶段开始（调用方负责 commit，保证崩溃后节点日志可见）"""
        progress = dict(self.step_progress or {})
        progress[step_name] = {"status": "running", "started_at": now_china().isoformat()}
        self.step_progress = progress

    def finish_step(self, step_name: str, metrics: Optional[dict] = None) -> None:
        """记录阶段完成"""
        progress = dict(self.step_progress or {})
        node = progress.get(step_name) if isinstance(progress.get(step_name), dict) else {}
        node["status"] = "done"
        node["finished_at"] = now_china().isoformat()
        if metrics:
            node["metrics"] = metrics
        progress[step_name] = node
        self.step_progress = progress

    def fail_step(self, step_name: str, error: str) -> None:
        """记录阶段失败"""
        progress = dict(self.step_progress or {})
        node = progress.get(step_name) if isinstance(progress.get(step_name), dict) else {}
        node["status"] = "failed"
        node["error"] = error
        node["finished_at"] = now_china().isoformat()
        progress[step_name] = node
        self.step_progress = progress
