"""模型配置端口（ModelConfigPort）与模型凭证数据类。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:  # 仅类型注解用，避免端口模块运行时依赖 ai_models 实现
    from novamind.shared.ai_models.base_model import BaseEmbedding, BaseLLM, BaseRerank


@dataclass
class ModelCredentials:
    """模型凭证（用于创建 AI 客户端）。"""

    protocol: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    extra_config: Optional[Dict[str, Any]] = None


@runtime_checkable
class ModelConfigPort(Protocol):
    """模型配置端口：客户端创建 + 查询面（``ModelConfigService`` 结构化满足）。"""

    async def get_llm_client_by_model(
        self, user_id: int, model: str
    ) -> "BaseLLM":
        """根据模型名称获取 LLM 客户端。"""
        ...

    async def get_vlm_client_by_model(
        self, user_id: int, model: str
    ) -> "BaseLLM":
        """根据模型名称获取 VLM 客户端（复用 LLM 工厂）。"""
        ...

    async def get_embedding_client_by_model(
        self, user_id: int, model: str
    ) -> "BaseEmbedding":
        """根据模型名称获取 Embedding 客户端。"""
        ...

    async def get_rerank_client_by_model(
        self, user_id: int, model: str
    ) -> "BaseRerank":
        """根据模型名称获取 Rerank 客户端。"""
        ...

    async def get_user_default_model_name(
        self, user_id: int, model_type: str
    ) -> Optional[str]:
        """获取用户在指定类型下配置的第一个模型名（作为用户默认）。"""
        ...

    async def list_available_models(
        self, user_id: int, model_type: str
    ) -> List[str]:
        """获取用户可用的模型名称列表（用于前端下拉框）。"""
        ...

    async def list_available_models_with_info(
        self, user_id: int
    ) -> Any:
        """获取可用模型的详细信息（按类型分组的 ModelInfo 列表）。"""
        ...

    async def get_credentials_by_model(
        self,
        user_id: int,
        model_type: str,
        model: str,
    ) -> Optional[ModelCredentials]:
        """根据模型名称获取凭证（含解密后的明文 api_key）。"""
        ...


__all__ = ["ModelConfigPort", "ModelCredentials"]