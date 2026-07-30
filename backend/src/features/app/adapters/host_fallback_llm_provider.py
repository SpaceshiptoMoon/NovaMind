"""FallbackLLMProvider 宿主适配器（resume 引擎）。

把宿主侧 ``ModelConfigService`` 包成引擎端口 ``FallbackLLMProvider`` 实例，供
``AutoProbingEngine`` 在主模型重试耗尽后取用户其他可用 LLM 客户端做降级调用。
resume 引擎不再直接 import ``user.services.model_config_service``，切断 resume
引擎 -> user feature 导入边（ModelConfigService 全量端口化见批次 5b/任务#36）。

行为对齐原 ``AutoProbingEngine._load_fallback_models``：列出用户 llm 模型配置，
排除当前主模型，逐个构造客户端；构造失败的模型静默跳过。
"""
from typing import List

from novamind_engine_core.ai_models.base_model import BaseLLM
from novamind_engine_core.engine_ports import FallbackLLMProvider


class HostFallbackLLMProvider:
    """FallbackLLMProvider 宿主实现：委托 ``ModelConfigService``。"""

    def __init__(self, model_config_service: object):
        self._svc = model_config_service

    async def load_fallback_clients(
        self, user_id: int, exclude_model: str
    ) -> List[BaseLLM]:
        svc = self._svc  # type: ignore[attr-defined]
        configs = await svc.repo.list_by_user(user_id, "llm")
        clients: List[BaseLLM] = []
        for cfg in configs:
            if cfg.model == exclude_model:
                continue
            try:
                client = await svc.get_llm_client_by_model(user_id, cfg.model)
                clients.append(client)
            except Exception:
                # 构造失败的模型静默跳过（与原实现一致）
                continue
        return clients


def as_fallback_llm_provider(model_config_service: object) -> FallbackLLMProvider:
    """构造 FallbackLLMProvider 实例（供装配点注入 AutoProbingEngine）。"""
    return HostFallbackLLMProvider(model_config_service)  # type: ignore[return-value]