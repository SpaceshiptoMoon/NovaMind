"""
Document task schemas.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class DocumentTaskItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="任务项ID")
    task_id: int = Field(..., description="任务ID")
    document_id: int = Field(..., description="文档ID")
    document_name: Optional[str] = Field(None, description="文档名（由后端按 document_id 关联 Documents.filename 填充，前端展示用）")
    kb_id: int = Field(..., description="知识库ID")
    space_id: int = Field(..., description="空间ID")
    status: int = Field(..., description="任务项状态")
    job_id: Optional[str] = Field(None, description="arq job ID")
    step_progress: Optional[Dict[str, Any]] = Field(None, description="步骤进度")
    pipeline_result: Optional[Dict[str, Any]] = Field(None, description="处理结果")
    error_message: Optional[str] = Field(None, description="错误信息")
    retry_count: int = Field(default=0, description="自动重试次数")
    queued_at: Optional[datetime] = Field(None, description="入队时间")
    started_at: Optional[datetime] = Field(None, description="开始处理时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    @field_serializer("status")
    def serialize_status(self, value) -> int:
        if hasattr(value, "value"):
            return value.value
        return int(value) if value is not None else 0


class DocumentTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="任务ID")
    space_id: int = Field(..., description="空间ID")
    kb_id: int = Field(..., description="知识库ID")
    creator_id: int = Field(..., description="创建人ID")
    action: int = Field(..., description="任务动作")
    status: int = Field(..., description="任务状态")
    pipeline_config: Optional[Dict[str, Any]] = Field(None, description="处理配置快照")
    total_count: int = Field(..., description="文档总数")
    task_summary: Optional[Dict[str, Any]] = Field(None, description="任务汇总")
    note: Optional[str] = Field(None, description="任务说明")
    error_message: Optional[str] = Field(None, description="任务级错误")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    items: List[DocumentTaskItemResponse] = Field(default_factory=list, description="任务子项")

    @field_serializer("action", "status")
    def serialize_int_enum(self, value) -> int:
        if hasattr(value, "value"):
            return value.value
        return int(value) if value is not None else 0


class DocumentTaskListResponse(BaseModel):
    items: List[DocumentTaskResponse] = Field(..., description="任务列表")
    total: int = Field(..., description="总数")


class DocumentTaskItemListResponse(BaseModel):
    items: List[DocumentTaskItemResponse] = Field(..., description="任务项列表")
    total: int = Field(..., description="总数")


class DocumentTaskBatchResponse(DocumentTaskResponse):
    pass


class DocumentTaskBatchListResponse(DocumentTaskListResponse):
    pass


class TaskStatusResponse(BaseModel):
    document_id: int = Field(..., description="文档ID")
    status: int = Field(..., description="当前状态")
    status_name: str = Field(..., description="状态名")
    step_progress: Optional[Dict[str, Any]] = Field(None, description="步骤进度")
    error_message: Optional[str] = Field(None, description="错误信息")
