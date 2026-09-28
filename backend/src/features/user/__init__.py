"""用户模块公共面：认证、用户/角色管理、模型与搜索配置聚合导出。"""

# API 路由
from novamind.features.user.api import router

# 数据模型
from novamind.features.user.models.user import User
from novamind.features.user.models.user_model_config import ModelType, UserModelConfig

# 仓储层
from novamind.features.user.repository import UserRepository
from novamind.features.user.repository.model_config_repository import ModelConfigRepository

# Schema - 模型配置
from novamind.features.user.schemas.model_config_schema import (
    ModelConfigCreate,
    ModelConfigListResponse,
    ModelConfigResponse,
    ModelConfigUpdate,
    ModelTestRequest,
    ModelTestResponse,
)

# Schema - 用户
from novamind.features.user.schemas.user_schema import (
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)

# 服务层
from novamind.features.user.services import UserService
from novamind.features.user.services.auth_service import AuthService
from novamind.features.user.services.model_config_service import ModelConfigService

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
