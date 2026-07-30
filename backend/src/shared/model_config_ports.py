"""模型配置端口（ModelConfigPort）与模型凭证数据类。

批次 5b：把 ``ModelConfigService`` 的**客户端创建/查询面**抽成中立端口，供各 feature
服务经构造器注入 ``ModelConfigPort``，不再直接 import ``user.services.model_config_service``
（切断 ``features.<X> → features.user.services`` 导入边）。CRUD/test 方法仅
``user/api/model_config_routes.py`` 用，属宿主自有，不进端口——具体 ``ModelConfigService``
结构化满足本协议，装配点（``features/<X>/api/dependencies.py``、arq worker 入口、
模块级静态助手函数）仍构造 ``ModelConfigService(db)`` 作为 ``ModelConfigPort`` 注入。

端口覆盖 8 个调用面方法：
  - ``get_llm_client_by_model`` / ``get_vlm_client_by_model`` / ``get_embedding_client_by_model``
    / ``get_rerank_client_by_model``：按模型名取对应 AI 客户端。
  - ``get_user_default_model_name``：取用户在某类型下配置的首个模型名（作为默认）。
  - ``list_available_models`` / ``list_available_models_with_info``：列可用模型。
  - ``get_credentials_by_model``：取模型凭证（ASR/VLM 等需明文凭证的场景）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:  # 仅类型注解用，避免端口模块运行时依赖 ai_models 实现
    from novamind.shared.ai_models.base_model import BaseEmbedding, BaseLLM, BaseRerank


@dataclass
class ModelCredentials:
    """模型凭证（用于创建 AI 客户端）。

    包含创建 AI 客户端所需的所有信息。原定义在 ``model_config_service.py``，
    批次 5b 迁到本中立位置，原模块 re-export 保向后兼容。
    """

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