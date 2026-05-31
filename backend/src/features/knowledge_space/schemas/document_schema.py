"""
文档 Schema

定义文档的请求和响应模型
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_serializer, computed_field



class DocumentResponse(BaseModel):
    """文档响应"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int = Field(..., description="文档ID")
    space_id: int = Field(..., description="所属空间ID")
    kb_id: int = Field(..., description="所属知识库ID")
    uploader_id: int = Field(..., description="上传者ID")
    filename: str = Field(..., description="原始文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小(字节)")
    file_hash: str = Field(..., description="文件哈希")
    status: int = Field(..., description="处理状态")
    doc_metadata: Optional[Dict[str, Any]] = Field(None, description="文档元数据")
    status_info: Optional[Dict[str, Any]] = Field(None, description="状态详情（错误信息、重试次数等）")
    created_at: datetime = Field(..., description="上传时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    processing_started_at: Optional[datetime] = Field(None, description="处理开始时间")
    processed_at: Optional[datetime] = Field(None, description="处理完成时间")

    @field_serializer('status')
    def serialize_status(self, value) -> int:
        """序列化状态枚举为整数"""
        if hasattr(value, 'value'):
            return value.value
        return int(value)

    @computed_field
    @property
    def retry_count(self) -> int:
        """从 status_info 中提取重试次数"""
        if self.status_info:
            return self.status_info.get("retry_count", 0)
        return 0

    @computed_field
    @property
    def error_message(self) -> Optional[str]:
        """从 status_info 中提取错误信息"""
        if self.status_info:
            return self.status_info.get("error_message")
        return None

    @computed_field
    @property
    def chunk_count(self) -> int:
        """从 doc_metadata 中提取分块数量"""
        if self.doc_metadata:
            return self.doc_metadata.get("chunk_count", 0)
        return 0

    @computed_field
    @property
    def token_count(self) -> int:
        """从 doc_metadata 中提取 Token 总数"""
        if self.doc_metadata:
            return self.doc_metadata.get("token_count", 0)
        return 0


class DocumentListResponse(BaseModel):
    """文档列表响应"""
    items: List[DocumentResponse] = Field(..., description="文档列表")
    total: int = Field(..., description="总数")
    skip: int = Field(..., description="跳过数量")
    limit: int = Field(..., description="返回数量")


class ChunkResponse(BaseModel):
    """分块响应（匹配 ES 返回的数据结构）"""
    chunk_id: str = Field(..., description="分块ID")
    document_id: int = Field(..., description="所属文档ID")
    chunk_index: int = Field(0, description="分块索引")
    content: str = Field(..., description="分块内容")
    score: Optional[float] = Field(None, description="检索得分")
    has_embedding: bool = Field(False, description="是否已向量化")
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据")
    file_info: Optional[Dict[str, Any]] = Field(None, description="文件信息")
    questions: Optional[List[str]] = Field(None, description="假设性问题列表")
    created_at: Optional[str] = Field(None, description="创建时间")
    chunk_type: Optional[str] = Field(None, description="分块类型: text/image")
    image_url: Optional[str] = Field(None, description="图片预览 URL（图片类型分块）")


class DocumentDetailResponse(DocumentResponse):
    """文档详情响应（包含分块）"""
    chunks: List[ChunkResponse] = Field(default_factory=list, description="分块列表")


class DocumentUploadResponse(BaseModel):
    """文档上传响应"""
    document_id: int = Field(..., description="文档ID")
    filename: str = Field(..., description="文件名")
    status: str = Field(..., description="处理状态")
    message: str = Field(default="文档上传成功，等待拆分解析", description="消息")


class FailedFileItem(BaseModel):
    """批量上传失败的文件项"""
    filename: str = Field(..., description="文件名")
    error: str = Field(..., description="失败原因")


class DocumentBatchUploadResponse(BaseModel):
    """批量上传响应"""
    total: int = Field(..., description="上传文件总数")
    success: List[DocumentUploadResponse] = Field(default_factory=list, description="上传成功的文档列表")
    failed: List[FailedFileItem] = Field(default_factory=list, description="上传失败的文件列表")


# ========== 拆分解析相关 Schema ==========


class DocumentProcessRequest(BaseModel):
    """单文档/重新解析请求"""


class DocumentBatchProcessRequest(BaseModel):
    """批量拆分解析请求"""
    document_ids: Optional[List[int]] = Field(
        default=None,
        max_length=100,
        description="文档ID列表（最多100个），为空则处理全部未处理文档",
    )


class DocumentProcessResponse(BaseModel):
    """单文档处理响应"""
    document_id: int
    status: str = "processing"
    message: str = "文档已开始处理"


class DocumentCancelResponse(BaseModel):
    """文档取消响应"""
    document_id: int
    status: str = "cancelling"
    message: str = "取消请求已发送"


class DocumentBatchProcessResponse(BaseModel):
    """批量处理响应"""
    total: int
    success: int
    failed: int
    skipped: int
    results: List[Dict[str, Any]]
