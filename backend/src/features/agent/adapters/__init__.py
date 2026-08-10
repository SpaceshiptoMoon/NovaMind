"""
Agent 引擎宿主适配层，实现引擎端口协议，桥接宿主 ORM / 配置 / 外部服务。
"""
from novamind.features.agent.adapters.web_search_adapter import HostWebSearchPort
from novamind.features.agent.adapters.knowledge_search_adapter import (
    HostKnowledgeSearchPort,
)
from novamind.features.agent.adapters.memory_store_adapter import (
    HostMemorySearchPort,
    HostMemoryStorePort,
)
from novamind.shared.prompts.host_prompt_provider import HostPromptProvider

__all__ = [
    "HostWebSearchPort",
    "HostKnowledgeSearchPort",
    "HostMemoryStorePort",
    "HostMemorySearchPort",
    "HostPromptProvider",
]