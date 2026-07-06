"""
DocumentTask Schema

定义文档处理任务请求/响应模型。
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_serializer


# ========== Task Status ==========

class TaskStatusSchema(BaseModel):
    """任务状态信息"""
    status: int = Field(..., description="状态码: 0-待处理, 1-处理中, 2-已完成, 3-失败, 4-已取消")
    name: str = Field(..., description="状态名称")
    label: str = Field(..., description="状态展示文本")


# ========== Response ==========

class DocumentTaskResponse(BaseModel):
    """任务响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="任务ID")
    document_id: int = Field(..., description="文档ID")
    kb_id: int = Field(..., description="知识库ID")
    space_id: int = Field(..., description="空间ID")

    status: int = Field(..., description="任务状态: 0-待处理, 1-处理中, 2-已完成, 3-失败, 4-已取消")
    job_id: Optional[str] = Field(None, description="arq job ID")

    pipeline_config: Optional[Dict[str, Any]] = Field(None, description="处理配置快照")
    step_progress: Optional[Dict[str, Any]] = Field(None, description="步骤进度")
    pipeline_result: Optional[Dict[str, Any]] = Field(None, description="处理结果")

    error_message: Optional[str] = Field(None, description="错误信息")
    retry_count: int = Field(default=0, description="重试次数")

    queued_at: Optional[datetime] = Field(None, description="入队时间")
    started_at: Optional[datetime] = Field(None, description="开始处理时间")
    completed_at: Optional[datetime] = Field(None, description="完成/失败时间")

    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    @field_serializer("status")
    def serialize_status(self, value) -> int:
        if hasattr(value, "value"):
            return value.value
        return int(value) if value is not None else 0


class DocumentTaskListResponse(BaseModel):
    """任务列表响应"""
    tasks: List[DocumentTaskResponse] = Field(..., description="任务列表")
    total: int = Field(..., description="总数")


class TaskStatusResponse(BaseModel):
    """任务状态摘要响应"""
    document_id: int = Field(..., description="文档ID")
    status: int = Field(..., description="当前状态")
    status_name: str = Field(..., description="状态名称")
    step_progress: Optional[Dict[str, Any]] = Field(None, description="步骤进度")
    error_message: Optional[str] = Field(None, description="错误信息")
