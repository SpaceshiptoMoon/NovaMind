"""
用户搜索配置 Pydantic Schema

设计原则对齐 ``model_config_schema``：
- 凭证分离：只存 provider 凭证（api_key），业务参数进 extra_config
- api_key 响应脱敏（``****`` if set else ``""``），对齐
  ``model_config_service._build_response``（:908-919）
- provider 白名单校验 ``{tavily, serpapi, duckduckgo}``
- 更新时 api_key 留空（None）= 不改，与 model_config 约定一致
"""
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, Dict, Any, List
from datetime import datetime


# ========== 请求/响应模型 ==========

class SearchConfigBase(BaseModel):
    """搜索配置基础字段"""

    provider: str = Field(
        ...,
        description="搜索服务商: tavily/serpapi/duckduckgo",
        examples=["tavily", "serpapi", "duckduckgo"],
    )
    api_key: Optional[str] = Field(
        None,
        description="API Key（duckduckgo 可空）",
        examples=["tvly-xxxxxxxx"],
    )
    extra_config: Optional[Dict[str, Any]] = Field(
        None,
        description="扩展配置（max_results/search_depth/timeout/include_domains 等）",
        examples=[{"max_results": 10, "search_depth": "basic"}],
    )
    is_primary: bool = Field(False, description="是否设为首选 provider")

    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """验证搜索服务商白名单"""
        allowed = {"tavily", "serpapi", "duckduckgo"}
        if v.lower() not in allowed:
            raise ValueError(f"不支持的搜索服务商: {v}，支持: {allowed}")
        return v.lower()


class SearchConfigCreate(SearchConfigBase):
    """创建搜索配置请求"""


class SearchConfigUpdate(BaseModel):
    """更新搜索配置请求

    api_key 留空（None）= 不修改（保留原密文）；显式传空串视为清空。
    """

    api_key: Optional[str] = Field(None, description="API Key（留空表示不修改）")
    extra_config: Optional[Dict[str, Any]] = Field(None, description="扩展配置")
    is_primary: Optional[bool] = Field(None, description="是否设为首选 provider")


class SearchConfigResponse(BaseModel):
    """搜索配置响应（API Key 已脱敏）"""

    id: int = Field(..., description="配置 ID")
    user_id: int = Field(..., description="用户 ID")
    provider: str = Field(..., description="搜索服务商")
    api_key: Optional[str] = Field(None, description="API Key（已脱敏）")
    extra_config: Optional[Dict[str, Any]] = Field(None, description="扩展配置")
    is_primary: bool = Field(..., description="是否首选")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(from_attributes=True)


class SearchConfigListResponse(BaseModel):
    """搜索配置列表响应"""

    total: int = Field(..., description="总数")
    items: List[SearchConfigResponse] = Field(..., description="配置列表")


# ========== 连接测试 ==========

class SearchTestRequest(BaseModel):
    """搜索连接测试请求（提交凭据实搜一次验证，不入库）"""

    provider: str = Field(
        ...,
        description="搜索服务商: tavily/serpapi/duckduckgo",
    )
    api_key: Optional[str] = Field(
        None,
        description="API Key（duckduckgo 可空）",
    )
    extra_config: Optional[Dict[str, Any]] = Field(
        None,
        description="扩展配置",
    )

    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = {"tavily", "serpapi", "duckduckgo"}
        if v.lower() not in allowed:
            raise ValueError(f"不支持的搜索服务商: {v}")
        return v.lower()


class SearchTestResponse(BaseModel):
    """搜索连接测试响应"""

    success: bool = Field(..., description="测试是否成功")
    message: str = Field(..., description="测试结果消息")
    latency_ms: Optional[float] = Field(None, description="响应延迟（毫秒）")
    results_count: int = Field(0, description="返回结果数")