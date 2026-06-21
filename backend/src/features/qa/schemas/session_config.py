"""
会话配置相关的 Pydantic 模型
"""
from typing import Optional, Literal, List
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
    threshold: int = Field(default=3000, ge=500, le=200000, description="触发压缩的 token 阈值")
    target_tokens: int = Field(default=500, ge=100, le=2000, description="压缩后的目标 token 数")
    keep_recent: int = Field(default=2, ge=0, le=10, description="保留的最近消息数")
    custom_prompt: Optional[str] = Field(default=None, max_length=2000, description="自定义摘要提示词")


# ========== RAG 绑定配置结构（会话级自动 RAG） ==========

class RagBindingConfig(BaseModel):
    """知识库绑定配置（会话级自动 RAG）"""
    space_id: Optional[int] = Field(default=None, description="知识空间ID")
    kb_ids: List[int] = Field(default_factory=list, description="绑定的知识库ID列表")
    auto_rag: bool = Field(default=False, description="是否启用会话级自动 RAG")
    refusal_enabled: bool = Field(default=False, description="是否启用分级拒答（检索为空拒答、低分标记）")
    score_threshold: float = Field(default=0.3, ge=0.0, le=1.0, description="低置信度阈值（单库模式生效）")
    search_mode: str = Field(default="content_hybrid", description="检索模式（默认混合）")
    top_k: int = Field(default=5, ge=1, le=20, description="检索返回条数")


# ========== 模型生成参数配置结构（会话级持久化） ==========

class LlmConfig(BaseModel):
    """模型生成参数配置（会话级持久化）

    注意：llm_model / enable_thinking 由前端请求传，不在此列。
    """
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8192, description="最大生成token数（None 用默认 2048）")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0, description="温度（None 用默认 0.7）")
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Top-P（None 用默认 0.8）")
    system_prompt: Optional[str] = Field(default=None, max_length=4000, description="系统提示词（None 用后端 QA 模板）")


# ========== 请求/响应模型 ==========

class SessionConfigCreate(BaseModel):
    """创建会话配置请求（只包含压缩配置）"""
    compression: CompressionConfig = Field(
        default_factory=CompressionConfig,
        description="压缩配置"
    )


class SessionConfigCompressionUpdate(BaseModel):
    """更新会话压缩配置请求（支持反复修改）"""
    compression: CompressionConfig = Field(..., description="压缩配置")


class SessionConfigLlmUpdate(BaseModel):
    """更新会话模型生成参数配置请求（支持反复修改）"""
    llm_config: LlmConfig = Field(..., description="模型生成参数配置")


class SessionConfigRagUpdate(BaseModel):
    """更新会话知识库绑定配置请求（独立于压缩配置，可反复修改）"""
    rag: RagBindingConfig = Field(..., description="知识库绑定配置")


class SessionConfigResponse(BaseModel):
    """会话配置响应"""
    id: int
    session_id: str
    user_id: int
    compression_config: dict
    kb_bindings: Optional[dict] = Field(default=None, description="知识库绑定配置（会话级自动 RAG）")
    llm_config: Optional[dict] = Field(default=None, description="模型生成参数配置（会话级持久化）")

    # 时间戳
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
