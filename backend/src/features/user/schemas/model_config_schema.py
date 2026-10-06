"""用户模型配置 Schema：凭证分离设计，模型名称引用 + extra_config 扩展。"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ========== 凭据/端点通用格式守卫（mixin） ==========

# 声明类枚举键 → 合法值集合。与 quirks 层的覆盖白名单保持同源语义：
# 边界显式拒绝非法值（fail fast），不再静默吞掉让错误漏到厂商侧变成神秘 401。
_DECLARED_ENUM_KEYS: dict[str, frozenset[str]] = {
    "auth_type": frozenset({"api_key", "bearer"}),
}


class _CredentialGuards(BaseModel):
    """凭据/端点/声明字段的通用格式守卫（厂商无关）。

    拦截「字段互串」类输入错误（如把 Base URL 粘进 API Key 框）与非法声明值，
    在系统边界 fail fast 并给出可读报错，而不是放行到厂商侧变成鉴权失败。

    note: 字段在子类上定义，校验器用 ``check_fields=False`` 声明后由子类自动接入。
    """

    @field_validator('api_key', check_fields=False)
    @classmethod
    def _guard_api_key_not_url(cls, v: str | None) -> str | None:
        """API Key 槽位拒绝 URL 形状的值：凭据不会以 http(s):// 开头。"""
        if v and v.strip().lower().startswith(("http://", "https://")):
            raise ValueError(
                "API Key 字段填入了 URL——请填凭据本体（API Key 或 token），"
                "Base URL 请填到 Base URL 字段"
            )
        return v

    @field_validator('base_url', check_fields=False)
    @classmethod
    def _guard_base_url_scheme(cls, v: str | None) -> str | None:
        """Base URL 必须是 http(s) 地址：拦截把 URL 粘进其他字段后的连锁互串。"""
        if v and not v.strip().lower().startswith(("http://", "https://")):
            raise ValueError(
                f"Base URL 须以 http:// 或 https:// 开头，收到: {v[:50]!r}"
            )
        return v

    @field_validator('extra_config', check_fields=False)
    @classmethod
    def _guard_declared_enum_values(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """声明类枚举键（auth_type 等）值必须在合法集合内，否则显式报错。

        与 quirks.resolve_quirks 的静默忽略不同：用户显式填了键就是明确的
        意图表达，拼错值应立刻报错而非静默落默认（那是排查地狱的源头）。
        """
        if not v:
            return v
        for key, allowed in _DECLARED_ENUM_KEYS.items():
            if key in v and v[key] not in allowed:
                raise ValueError(
                    f"扩展配置 {key}={v[key]!r} 非法，合法值: {sorted(allowed)}"
                )
        return v


# ========== 请求/响应模型 ==========

class ModelConfigBase(_CredentialGuards, BaseModel):
    """模型配置基础字段"""

    model_type: str = Field(
        ...,
        description="模型类型: llm/embedding/rerank",
        examples=["llm", "embedding", "rerank"]
    )
    protocol: str = Field(
        ...,
        description="通信协议: openai/openai_video/anthropic/ollama/transformers",
        min_length=1,
        max_length=50,
        examples=["openai", "openai_video", "anthropic"]
    )
    model: str = Field(
        ...,
        description="模型名称",
        examples=["gpt-4o", "text-embedding-3-small"]
    )
    base_url: str | None = Field(
        None,
        description="API Base URL",
        examples=["https://api.openai.com/v1"]
    )
    api_key: str | None = Field(
        None,
        description="API Key",
        examples=["sk-xxxxxxxx"]
    )
    extra_config: dict[str, Any] | None = Field(
        None,
        description=(
            "扩展配置（如 dimension、timeout、stream_only/force_thinking/"
            "auth_type 怪癖声明）；anthropic 协议下 auth_type 指定凭据头语义："
            "api_key=x-api-key 头（默认），bearer=Authorization Bearer 头"
            "（coding-plan token 类凭据需显式声明）"
        ),
        examples=[
            {"dimension": 1024, "endpoint": "https://custom.api"},
            {"auth_type": "bearer"},
        ],
    )

    @field_validator('model_type')
    @classmethod
    def validate_model_type(cls, v: str) -> str:
        """验证模型类型属白名单并归一为小写。

        Args:
            v: 待校验的模型类型字符串。

        Returns:
            归一为小写后的模型类型。

        Raises:
            ValueError: 不在 llm/embedding/rerank/vlm/asr 白名单内。
        """
        allowed = {"llm", "embedding", "rerank", "vlm", "asr"}
        if v.lower() not in allowed:
            raise ValueError(f"不支持的模型类型: {v}，支持的类型: {allowed}")
        return v.lower()


class ModelConfigCreate(ModelConfigBase):
    """创建模型配置请求"""


class ModelConfigUpdate(_CredentialGuards, BaseModel):
    """更新模型配置请求"""

    protocol: str | None = Field(
        None,
        description="通信协议",
        min_length=1,
        max_length=50
    )
    model: str | None = Field(None, description="模型名称")
    base_url: str | None = Field(None, description="API Base URL")
    api_key: str | None = Field(None, description="API Key")
    extra_config: dict[str, Any] | None = Field(None, description="扩展配置")


class ModelConfigResponse(BaseModel):
    """模型配置响应（API Key 已脱敏）"""

    id: int = Field(..., description="配置 ID")
    user_id: int = Field(..., description="用户 ID")
    model_type: str = Field(..., description="模型类型")
    protocol: str = Field(..., description="通信协议")
    model: str = Field(..., description="模型名称")
    base_url: str | None = Field(None, description="API Base URL")
    api_key: str | None = Field(None, description="API Key（已脱敏）")
    extra_config: dict[str, Any] | None = Field(None, description="扩展配置")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(from_attributes=True)


class ModelConfigListResponse(BaseModel):
    """模型配置列表响应"""

    total: int = Field(..., description="总数")
    items: list[ModelConfigResponse] = Field(..., description="配置列表")


# ========== 连接测试 ==========

class ModelTestRequest(_CredentialGuards, BaseModel):
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
    base_url: str | None = Field(
        None,
        description="API Base URL"
    )
    api_key: str = Field(
        ...,
        description="API Key"
    )
    extra_config: dict[str, Any] | None = Field(
        None,
        description="扩展配置（如 stream_only/force_thinking 怪癖声明）；仅后端内部与测试请求使用",
    )

    @field_validator('model_type')
    @classmethod
    def validate_model_type(cls, v: str) -> str:
        """校验模型类型属白名单（llm/embedding/rerank/vlm/asr）并归一为小写。

        Args:
            v: 待校验的模型类型字符串。

        Returns:
            归一为小写后的模型类型。

        Raises:
            ValueError: 不在白名单内。
        """
        allowed = {"llm", "embedding", "rerank", "vlm", "asr"}
        if v.lower() not in allowed:
            raise ValueError(f"不支持的模型类型: {v}")
        return v.lower()


class ModelTestResponse(BaseModel):
    """模型连接测试响应"""

    success: bool = Field(..., description="测试是否成功")
    message: str = Field(..., description="测试结果消息")
    latency_ms: float | None = Field(None, description="响应延迟（毫秒）")
    detected_dimension: int | None = Field(None, description="自动检测的 Embedding 向量维度")


# ========== 可用模型列表 ==========

class ModelConfigAvailableModelsResponse(BaseModel):
    """可用模型列表响应（供前端下拉框）"""

    llm: list[str] = Field(default_factory=list, description="可用的 LLM 模型名称")
    embedding: list[str] = Field(default_factory=list, description="可用的 Embedding 模型名称")
    rerank: list[str] = Field(default_factory=list, description="可用的 Rerank 模型名称")
    vlm: list[str] = Field(default_factory=list, description="可用的 VLM 视觉模型名称")
    asr: list[str] = Field(default_factory=list, description="可用的 ASR 语音识别模型名称")


class ModelInfo(BaseModel):
    """模型信息"""

    model: str = Field(..., description="模型名称")
    protocol: str = Field(..., description="通信协议")


class AvailableModelsWithInfoResponse(BaseModel):
    """可用模型详细信息响应"""

    llm: list[ModelInfo] = Field(default_factory=list, description="LLM 模型列表")
    embedding: list[ModelInfo] = Field(default_factory=list, description="Embedding 模型列表")
    rerank: list[ModelInfo] = Field(default_factory=list, description="Rerank 模型列表")
    vlm: list[ModelInfo] = Field(default_factory=list, description="VLM 视觉模型列表")
    asr: list[ModelInfo] = Field(default_factory=list, description="ASR 语音识别模型列表")


@dataclass
class ModelCredentials:
    """模型凭证（用于创建 AI 客户端）。批次 3.6 从 shared/model_config_ports.py 迁入。"""

    protocol: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    extra_config: dict | None = None
