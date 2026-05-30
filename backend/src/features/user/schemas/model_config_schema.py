"""
用户模型配置 Pydantic Schema

设计原则：
- 凭证分离：只存储连接凭证（api_key、base_url），不存储业务参数
- 模型名称引用：前端传模型名称（如 llm_model="gpt-4o"），后端根据名称查找凭证
- 扩展配置存储在 extra_config 中（如 dimension、endpoint 等）
"""
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, Dict, Any, List
from datetime import datetime

# ========== 请求/响应模型 ==========

class ModelConfigBase(BaseModel):
    """模型配置基础字段"""

    model_type: str = Field(
        ...,
        description="模型类型: llm/embedding/rerank",
        examples=["llm", "embedding", "rerank"]
    )
    protocol: str = Field(
        ...,
        description="通信协议: openai/anthropic/ollama/transformers",
        min_length=1,
        max_length=50,
        examples=["openai", "anthropic"]
    )
    model: str = Field(
        ...,
        description="模型名称",
        examples=["gpt-4o", "text-embedding-3-small"]
    )
    base_url: Optional[str] = Field(
        None,
        description="API Base URL",
        examples=["https://api.openai.com/v1"]
    )
    api_key: Optional[str] = Field(
        None,
        description="API Key",
        examples=["sk-xxxxxxxx"]
    )
    extra_config: Optional[Dict[str, Any]] = Field(
        None,
        description="扩展配置（如 dimension、endpoint 等）",
        examples=[{"dimension": 1024, "endpoint": "https://custom.api"}]
    )

    @field_validator('model_type')
    @classmethod
    def validate_model_type(cls, v: str) -> str:
        """验证模型类型"""
        allowed = {"llm", "embedding", "rerank", "vlm", "multimodal_embedding"}
        if v.lower() not in allowed:
            raise ValueError(f"不支持的模型类型: {v}，支持的类型: {allowed}")
        return v.lower()


class ModelConfigCreate(ModelConfigBase):
    """创建模型配置请求"""


class ModelConfigUpdate(BaseModel):
    """更新模型配置请求"""

    protocol: Optional[str] = Field(
        None,
        description="通信协议",
        min_length=1,
        max_length=50
    )
    model: Optional[str] = Field(None, description="模型名称")
    base_url: Optional[str] = Field(None, description="API Base URL")
    api_key: Optional[str] = Field(None, description="API Key")
    extra_config: Optional[Dict[str, Any]] = Field(None, description="扩展配置")


class ModelConfigResponse(BaseModel):
    """模型配置响应（API Key 已脱敏）"""

    id: int = Field(..., description="配置 ID")
    user_id: Optional[int] = Field(None, description="用户 ID（NULL 表示系统配置）")
    model_type: str = Field(..., description="模型类型")
    protocol: str = Field(..., description="通信协议")
    model: str = Field(..., description="模型名称")
    base_url: Optional[str] = Field(None, description="API Base URL")
    api_key: Optional[str] = Field(None, description="API Key（已脱敏）")
    extra_config: Optional[Dict[str, Any]] = Field(None, description="扩展配置")
    is_system: bool = Field(default=False, description="是否为系统配置")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(from_attributes=True)


class ModelConfigListResponse(BaseModel):
    """模型配置列表响应"""

    total: int = Field(..., description="总数")
    items: List[ModelConfigResponse] = Field(..., description="配置列表")


# ========== 连接测试 ==========

class ModelTestRequest(BaseModel):
    """模型连接测试请求"""

    model_type: str = Field(
        ...,
        description="模型类型: llm/embedding/rerank"
    )
    protocol: str = Field(
        default="openai",
        description="通信协议: openai/anthropic/ollama/transformers"
    )
    model: str = Field(
        ...,
        description="模型名称"
    )
    base_url: Optional[str] = Field(
        None,
        description="API Base URL"
    )
    api_key: str = Field(
        ...,
        description="API Key"
    )

    @field_validator('model_type')
    @classmethod
    def validate_model_type(cls, v: str) -> str:
        allowed = {"llm", "embedding", "rerank", "vlm", "multimodal_embedding"}
        if v.lower() not in allowed:
            raise ValueError(f"不支持的模型类型: {v}")
        return v.lower()


class ModelTestResponse(BaseModel):
    """模型连接测试响应"""

    success: bool = Field(..., description="测试是否成功")
    message: str = Field(..., description="测试结果消息")
    latency_ms: Optional[float] = Field(None, description="响应延迟（毫秒）")
    detected_dimension: Optional[int] = Field(None, description="自动检测的 Embedding 向量维度")


# ========== 可用模型列表 ==========

class AvailableModelsResponse(BaseModel):
    """可用模型列表响应（供前端下拉框）"""

    llm: List[str] = Field(default_factory=list, description="可用的 LLM 模型名称")
    embedding: List[str] = Field(default_factory=list, description="可用的 Embedding 模型名称")
    rerank: List[str] = Field(default_factory=list, description="可用的 Rerank 模型名称")
    vlm: List[str] = Field(default_factory=list, description="可用的 VLM 视觉模型名称")
    multimodal_embedding: List[str] = Field(default_factory=list, description="可用的多模态嵌入模型名称")


class ModelInfo(BaseModel):
    """模型信息"""

    model: str = Field(..., description="模型名称")
    protocol: str = Field(..., description="通信协议")
    is_system: bool = Field(default=False, description="是否为系统配置")


class AvailableModelsWithInfoResponse(BaseModel):
    """可用模型详细信息响应"""

    llm: List[ModelInfo] = Field(default_factory=list, description="LLM 模型列表")
    embedding: List[ModelInfo] = Field(default_factory=list, description="Embedding 模型列表")
    rerank: List[ModelInfo] = Field(default_factory=list, description="Rerank 模型列表")
    vlm: List[ModelInfo] = Field(default_factory=list, description="VLM 视觉模型列表")
    multimodal_embedding: List[ModelInfo] = Field(default_factory=list, description="多模态嵌入模型列表")
