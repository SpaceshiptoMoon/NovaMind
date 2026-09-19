"""
Wiki 页面 Pydantic schemas

请求/响应模型，遵循 *Response 设 from_attributes 的项目约定。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WikiPageResponse(BaseModel):
    """Wiki 页面（含正文，详情接口用）"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    title: str
    page_type: str
    status: str
    content: str
    summary: str
    aliases: List[str] = []
    category_path: List[str] = []
    source_refs: List[str] = []
    chunk_refs: List[str] = []
    in_links: List[str] = []
    out_links: List[str] = []
    version: int
    last_edit_source: str = ""
    created_at: datetime
    updated_at: datetime


class WikiPageListItem(BaseModel):
    """Wiki 页面列表项（轻量投影，不含正文）"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    title: str
    page_type: str
    status: str
    summary: str
    aliases: List[str] = []
    category_path: List[str] = []
    in_links: List[str] = []
    out_links: List[str] = []
    version: int
    last_edit_source: str = ""
    updated_at: datetime


class WikiPageListResponse(BaseModel):
    pages: List[WikiPageListItem]
    total: int
    page: int
    page_size: int


class WikiIndexGroup(BaseModel):
    """按类型分组的索引条目"""

    page_type: str
    total: int
    items: List[WikiPageListItem]


class WikiIndexResponse(BaseModel):
    """Wiki 首页索引（轻量列，40k 页 KB 也不传正文）"""

    groups: List[WikiIndexGroup]
    is_active: bool = False
    # index 页 intro（KB 简介，管道维护；目录列表本体按需装配不持久化）
    intro: str = ""


class WikiStatsResponse(BaseModel):
    total_pages: int
    pages_by_type: Dict[str, int] = {}
    total_links: int
    orphan_count: int
    is_active: bool = False


class WikiIngestStatusResponse(BaseModel):
    """生成状态（前端「生成中」轮询）"""

    status: str
    step_progress: Optional[Dict[str, Any]] = None
    pages_created: int = 0
    pages_updated: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class WikiPageSourcesResponse(BaseModel):
    """页面来源证据（文档级 + chunk 级）"""

    slug: str
    title: str
    source_documents: List[Dict[str, Any]] = Field(default_factory=list)
    chunk_refs: List[str] = []


class WikiPageSearchItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    title: str
    page_type: str
    summary: str


class WikiSearchResponse(BaseModel):
    items: List[WikiPageSearchItem]
    total: int
    query: str


# ==================== 写请求（P2） ====================


class WikiPageCreateRequest(BaseModel):
    """人工/Agent 创建页面"""

    slug: str = Field(..., min_length=1, max_length=255, description="KB 内唯一 slug，如 entity/acme 或 synthesis/xx")
    title: str = Field(..., min_length=1, max_length=512)
    content: str = Field(default="", max_length=500_000)
    summary: str = Field(default="", max_length=2000)
    page_type: str = Field(default="concept", description="entity/concept/synthesis/comparison（summary 由管道管理）")
    aliases: List[str] = Field(default_factory=list, max_length=50)
    category_path: List[str] = Field(default_factory=list, max_length=10)


class WikiPageUpdateRequest(BaseModel):
    """部分更新：缺席字段保持原值；version>0 时乐观锁校验"""

    title: Optional[str] = Field(default=None, min_length=1, max_length=512)
    content: Optional[str] = Field(default=None, max_length=500_000)
    summary: Optional[str] = Field(default=None, max_length=2000)
    page_type: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None, description="draft/published/archived")
    aliases: Optional[List[str]] = Field(default=None, max_length=50)
    category_path: Optional[List[str]] = Field(default=None, max_length=10)
    version: int = Field(default=0, ge=0, description="乐观锁：>0 时版本不符返回 409")


class WikiRevertRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=255)
    version: int = Field(..., ge=1)


class WikiRevertResponse(BaseModel):
    slug: str
    reverted_to_version: int
    new_version: int


class WikiRebuildRequest(BaseModel):
    """存量文档补算：不传 document_ids 则遍历 KB 全部已完成文档"""

    document_ids: Optional[List[int]] = Field(default=None, max_length=500)


# ==================== 图谱 / lint 闭环（P3） ====================


class WikiGraphNode(BaseModel):
    slug: str
    title: str
    page_type: str
    link_count: int


class WikiGraphEdge(BaseModel):
    source: str
    target: str


class WikiGraphMeta(BaseModel):
    mode: str
    total: int
    returned: int
    truncated: bool
    center: Optional[str] = None
    depth: Optional[int] = None


class WikiGraphResponse(BaseModel):
    nodes: List[WikiGraphNode]
    edges: List[WikiGraphEdge]
    meta: WikiGraphMeta


class WikiLintIssueItem(BaseModel):
    """lint 检出的问题"""

    slug: str
    # 对齐 WeKnora 六类：orphan_page / broken_link / stale_ref /
    # missing_cross_ref / empty_content / duplicate_slug（末者 MySQL 唯一
    # 约束下不可达，保留常量壳）
    issue_type: str
    severity: str = "warning"  # info / warning / error
    description: str
    # 另一方 slug（broken_link 的目标 / stale_ref 的文档标识）——AutoFix 用
    target_slug: str = ""
    auto_fixable: bool = False


class WikiLintResponse(BaseModel):
    issues: List[WikiLintIssueItem]
    checked_pages: int
    # 0-100 健康分（对齐 WeKnora HealthScore）
    health_score: int = 100
    summary: str = ""


class WikiAutoFixResponse(BaseModel):
    """AutoFix 执行结果"""

    fixed: int
    details: List[str] = []


class WikiIssueCreateRequest(BaseModel):
    """人工/Agent 报告页面问题"""

    slug: str = Field(..., min_length=1, max_length=255)
    issue_type: str = Field(..., description="mixed_entities/contradictory_facts/out_of_date/dead_link/orphan/other")
    description: str = Field(..., min_length=1, max_length=2000)
    reported_by: str = Field(default="user", max_length=100)


class WikiIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    issue_type: str
    description: str
    status: str
    reported_by: str
    created_at: datetime


class WikiIssueStatusUpdateRequest(BaseModel):
    status: str = Field(..., description="pending/ignored/resolved")
