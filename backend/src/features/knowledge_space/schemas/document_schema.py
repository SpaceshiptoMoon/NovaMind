"""
文档 Schema

定义文档的请求和响应模型
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_serializer, computed_field


# 延迟导入以避免循环依赖
def _get_document_task_response_type():
    from src.features.knowledge_space.schemas.document_task_schema import DocumentTaskResponse
    return DocumentTaskResponse


class DocumentResponse(BaseModel):
    """文档响应

    注意：status / error_message / retry_count 原为 Document 模型上的列，
    现已迁移至 DocumentTask。为保持向后兼容，这些字段改为 computed_field，
    从关联的 task 字段读取。若未预加载 task，则返回默认值。
    processing_started_at / processed_at 已移除，可通过 task.started_at / task.completed_at 获取。
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int = Field(..., description="文档ID")
    space_id: int = Field(..., description="所属空间ID")
    kb_id: int = Field(..., description="所属知识库ID")
    uploader_id: int = Field(..., description="上传者ID")
    filename: str = Field(..., description="原始文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小(字节)")
    file_hash: str = Field(..., description="文件哈希")
    doc_metadata: Optional[Dict[str, Any]] = Field(None, description="文档元数据")
    created_at: datetime = Field(..., description="上传时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    # 可选：预加载的最近一次 DocumentTask（列表接口通常不加载，详情接口可手动填充）
    task: Optional[Any] = Field(None, exclude=True, description="最近一次处理任务（用于计算 status/error_message）")

    @field_serializer('status')
    def serialize_status(self, value) -> int:
        """序列化状态枚举为整数"""
        if hasattr(value, 'value'):
            return value.value
        return int(value) if value is not None else 0

    @computed_field
    @property
    def status(self) -> int:
        """处理状态，从最近一次 DocumentTask 推导；无任务时默认 0 (PENDING)"""
        if self.task:
            task_status = getattr(self.task, 'status', None)
            if task_status is not None:
                if hasattr(task_status, 'value'):
                    return task_status.value
                return int(task_status)
        return 0

    @computed_field
    @property
    def retry_count(self) -> int:
        """重试次数，从最近一次 DocumentTask 读取"""
        if self.task:
            return getattr(self.task, 'retry_count', 0) or 0
        return 0

    @computed_field
    @property
    def error_message(self) -> Optional[str]:
        """错误信息，从最近一次 DocumentTask 读取"""
        if self.task:
            return getattr(self.task, 'error_message', None)
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
    chunk_type: Optional[str] = Field(None, description="分块类型: text/image/video/audio")
    image_url: Optional[str] = Field(None, description="图片预览 URL（已废弃，使用 media_url）")
    media_url: Optional[str] = Field(None, description="媒体文件预览 URL（图片/视频/音频）")


class DocumentDetailResponse(DocumentResponse):
    """文档详情响应（包含分块）"""
    chunks: List[ChunkResponse] = Field(default_factory=list, description="分块列表")


class DocumentUploadResponse(BaseModel):
    """文档上传响应"""
    document_id: int = Field(..., description="文档ID")
    filename: str = Field(..., description="文件名")
    # TODO: status 原从 Document.status 读取，现已迁移至 DocumentTask；暂时设 "uploaded" 占位
    status: str = Field(default="uploaded", description="处理状态（旧字段，从 DocumentTask 推导）")
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
    task_id: Optional[int] = None
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
