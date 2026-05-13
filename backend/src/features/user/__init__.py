"""
用户模块

提供用户管理和认证功能，支持：
- 用户注册、登录、登出
- JWT Token 认证
- 角色权限管理
- 用户信息管理
- 用户模型配置（LLM/Embedding/Rerank）
"""

# API 路由
from src.features.user.api import router

# 数据模型
from src.features.user.models.user import User
from src.features.user.models.user_model_config import UserModelConfig, ModelType

# 服务层
from src.features.user.services import UserService
from src.features.user.services.auth_service import AuthService
from src.features.user.services.model_config_service import ModelConfigService

# 仓储层
from src.features.user.repository import UserRepository
from src.features.user.repository.model_config_repository import ModelConfigRepository

# Schema - 用户
from src.features.user.schemas.user_schema import (
    UserCreate,
    UserLogin,
    UserUpdate,
    UserResponse,
    Token,
)

# Schema - 模型配置
from src.features.user.schemas.model_config_schema import (
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelConfigResponse,
    ModelConfigListResponse,
    ModelTestRequest,
    ModelTestResponse,
)

__all__ = [
    # API 路由
    "router",
    # 数据模型
    "User",
    "UserModelConfig",
    "ModelType",
    # 服务层
    "UserService",
    "AuthService",
    "ModelConfigService",
    # 仓储层
    "UserRepository",
    "ModelConfigRepository",
    # Schema - 用户
    "UserCreate",
    "UserLogin",
    "UserUpdate",
    "UserResponse",
    "Token",
    # Schema - 模型配置
    "ModelConfigCreate",
    "ModelConfigUpdate",
    "ModelConfigResponse",
    "ModelConfigListResponse",
    "ModelTestRequest",
    "ModelTestResponse",
]
