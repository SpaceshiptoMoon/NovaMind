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
