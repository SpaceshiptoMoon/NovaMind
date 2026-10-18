"""AI 聊天共享端点 schema（附件上传/健康检查/模型清单）。"""

from pydantic import BaseModel, Field


class HealthCheckResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(..., description="服务状态")
    message: str = Field(..., description="状态描述")


class ModelInfoResponse(BaseModel):
    """单个模型信息"""
    max_tokens: int = Field(..., description="最大生成token数")
    temperature: float = Field(..., description="默认温度参数")
    top_p: float = Field(..., description="默认Top-P参数")
    model_type: str = Field(default="llm", description="模型类型: llm/vlm")


class ChatAvailableModelsResponse(BaseModel):
    """可用模型列表响应"""
    models: dict[str, ModelInfoResponse] = Field(..., description="可用模型列表")


class UploadChatAttachmentResponse(BaseModel):
    """聊天附件上传响应"""
    attachment_id: int = Field(..., description="附件ID")
    filename: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小（字节）")
    message: str = Field(default="", description="提示信息")
