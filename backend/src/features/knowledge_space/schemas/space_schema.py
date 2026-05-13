"""
空间 Schema

定义知识空间的请求和响应模型

字段命名与数据库模型 (KnowledgeSpace) 保持一致:
- owner_id: 创建者ID
- visibility: 可见性 (SmallInteger: 0-私有, 1-团队, 2-公开)
- config: 空间配置 (JSON)
- status: 状态 (SmallInteger: 1-活跃, 2-归档, 3-删除)
"""

import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_serializer, field_validator
from enum import Enum

# 从模型层导入枚举（避免重复定义，保持一致）
from src.features.knowledge_space.models.knowledge_space import (
    SpaceVisibility,
    SpaceStatus,
)


class SpaceEmbeddingConfig(BaseModel):
    """空间级 Embedding 配置（dimension 由后端自动从模型配置表读取，前端无需传入）"""
    model: Optional[str] = Field(default=None, description="Embedding 模型名称")
    batch_size: int = Field(default=32, ge=1, le=128, description="批处理大小")
    normalize: bool = Field(default=True, description="是否归一化")


class SpaceConfig(BaseModel):
    """空间配置（对应模型中的 config JSON 字段）"""
    description: Optional[str] = Field(default="", max_length=2000, description="空间描述")
    tags: List[str] = Field(default_factory=list, max_length=20, description="标签（最多20个）")
    # Embedding 配置（空间级别，所有知识库共享）
    embedding: Optional[SpaceEmbeddingConfig] = Field(default=None, description="Embedding 配置")
    # 存储配置
    storage: Optional[Dict[str, Any]] = Field(None, description="存储配置")
    # UI 配置
    ui: Optional[Dict[str, Any]] = Field(None, description="UI配置")
    # 默认配置
    defaults: Optional[Dict[str, Any]] = Field(None, description="默认配置")
    # 限制配置
    limits: Optional[Dict[str, Any]] = Field(None, description="限制配置")

    @field_validator('storage', 'ui', 'defaults', 'limits')
    @classmethod
    def validate_json_field_size(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """验证 JSON 字段序列化后不超过 10KB，防止存储超大配置"""
        if v is not None:
            serialized = json.dumps(v, ensure_ascii=False)
            if len(serialized) > 10240:
                raise ValueError("JSON 配置字段不能超过 10KB")
        return v


class SpaceCreate(BaseModel):
    """创建空间请求"""
    name: str = Field(..., min_length=1, max_length=100, description="空间名称")
    visibility: SpaceVisibility = Field(default=SpaceVisibility.PRIVATE, description="可见性: 0-私有, 1-团队, 2-公开")
    config: Optional[SpaceConfig] = Field(None, description="空间配置")


class SpaceUpdate(BaseModel):
    """更新空间请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="空间名称")
    visibility: Optional[SpaceVisibility] = Field(None, description="可见性: 0-私有, 1-团队, 2-公开")
    config: Optional[SpaceConfig] = Field(None, description="空间配置")


class SpaceResponse(BaseModel):
    """空间响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="空间ID")
    name: str = Field(..., description="空间名称")
    owner_id: int = Field(..., description="创建者ID")
    visibility: int = Field(..., description="可见性: 0-私有, 1-团队, 2-公开")
    config: Optional[Dict[str, Any]] = Field(None, description="空间配置")
    status: int = Field(..., description="状态: 1-活跃, 2-归档, 3-删除")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    @field_serializer('visibility')
    def serialize_visibility(self, value) -> int:
        """序列化可见性枚举为整数"""
        if hasattr(value, 'value'):
            return value.value
        return int(value) if value is not None else 0

    @field_serializer('status')
    def serialize_status(self, value) -> int:
        """序列化状态枚举为整数"""
        if hasattr(value, 'value'):
            return value.value
        return int(value) if value is not None else 1

    def get_description(self) -> str:
        """获取描述（从 config 中提取）"""
        if self.config:
            return self.config.get("description", "")
        return ""


class SpaceListResponse(BaseModel):
    """空间列表响应"""
    items: List[SpaceResponse] = Field(..., description="空间列表")
    total: int = Field(..., description="总数")
    skip: int = Field(..., description="跳过数量")
    limit: int = Field(..., description="返回数量")


# ========== 配置管理 Schema ==========


class SpaceConfigUpdate(BaseModel):
    """空间配置部分更新请求（深度合并，只传要改的字段）"""
    description: Optional[str] = Field(None, max_length=2000, description="空间描述")
    tags: Optional[List[str]] = Field(None, max_length=20, description="标签")
    embedding: Optional[SpaceEmbeddingConfig] = Field(None, description="Embedding 配置")
    defaults: Optional[Dict[str, Any]] = Field(None, description="默认配置")
    limits: Optional[Dict[str, Any]] = Field(None, description="限制配置")

    @field_validator('defaults', 'limits')
    @classmethod
    def validate_json_field_size(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """验证 JSON 字段序列化后不超过 10KB"""
        if v is not None:
            serialized = json.dumps(v, ensure_ascii=False)
            if len(serialized) > 10240:
                raise ValueError("JSON 配置字段不能超过 10KB")
        return v


class SpaceConfigResponse(BaseModel):
    """空间配置响应"""
    space_id: int = Field(..., description="空间ID")
    name: str = Field(..., description="空间名称")
    config: SpaceConfig = Field(..., description="完整配置")
    stats: Dict[str, Any] = Field(..., description="统计信息")
