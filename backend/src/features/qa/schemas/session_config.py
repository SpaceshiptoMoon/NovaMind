"""
会话配置相关的 Pydantic 模型
"""
from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ========== 压缩配置结构 ==========

class CompressionConfig(BaseModel):
    """压缩配置"""
    enable_compression: bool = Field(default=True, description="是否启用压缩")
    strategy: Literal["summary", "sliding_window", "keep_recent", "truncate"] = Field(
        default="summary",
        description="压缩策略"
    )
    threshold: int = Field(default=3000, ge=500, le=10000, description="触发压缩的 token 阈值")
    target_tokens: int = Field(default=500, ge=100, le=2000, description="压缩后的目标 token 数")
    keep_recent: int = Field(default=2, ge=0, le=10, description="保留的最近消息数")
    custom_prompt: Optional[str] = Field(default=None, max_length=2000, description="自定义摘要提示词")


# ========== 请求/响应模型 ==========

class SessionConfigCreate(BaseModel):
    """创建会话配置请求（只包含压缩配置，创建后不可修改）"""
    compression: CompressionConfig = Field(
        default_factory=CompressionConfig,
        description="压缩配置（创建后不可修改）"
    )


class SessionConfigResponse(BaseModel):
    """会话配置响应"""
    id: int
    session_id: str
    user_id: int
    compression_config: dict

    # 时间戳
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
