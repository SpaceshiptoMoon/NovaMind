"""
引擎端口协议。
PromptProvider + FallbackLLMProvider，跨多引擎复用放 engines/ 顶层。
仅依赖 typing.Protocol，不依赖 feature/setting。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Protocol, runtime_checkable

if TYPE_CHECKING:
    # 仅用于类型注解（配合 `from __future__ import annotations` 惰性求值），
    # 避免 ports 顶部强 import ai_models。
    from novamind.shared.ai_models.base_model import BaseLLM


@runtime_checkable
class PromptProvider(Protocol):
    """提示词模板提供者协议。

    引擎通过字符串键取模板，**不 import 业务枚举**（如 PromptTemplate）。
    键的命名约定由各 feature 的 `*_prompts.py` 定义，宿主在装配时把
    `PromptManager` 实现注入引擎。

    设计决策（与 REFACTOR-qa-rag-pipeline 对齐）：键用字符串字面量，避免
    引擎库反向依赖宿主的提示词枚举，从而切断引擎 -> features 的导入边。
    """

    def get(self, key: str) -> str:
        """按键取原始模板字符串；键不存在应抛 ValueError。"""
        ...

    def format(self, key: str, **kwargs: Any) -> str:
        """按键取模板并用 kwargs 填充；缺参或键不存在应抛 ValueError。"""
        ...


@runtime_checkable
class FallbackLLMProvider(Protocol):
    """降级 LLM 提供者协议。

    引擎在主模型重试耗尽后，经此端口取用户其他可用 LLM 客户端做降级调用，
    不再直接 import ``user.services.model_config_service.ModelConfigService``
    （切断引擎 -> user feature 导入边；ModelConfigService 全量端口化见批次 5b/任务#36）。

    ``exclude_model`` 为当前主模型名，加载结果应排除之，避免降级回主模型。
    """

    async def load_fallback_clients(
        self, user_id: int, exclude_model: str
    ) -> List["BaseLLM"]:
        """加载用户可用的降级 LLM 客户端列表（排除主模型）。"""
        ...


__all__ = ["PromptProvider", "FallbackLLMProvider"]