"""
Agent 引擎宿主适配层

实现 ``engines/agent/ports.py`` 与 ``engines/ports.py`` 定义的端口协议，
桥接宿主 ORM/配置/外部服务。引擎（``engines/agent/*``）面向端口编程；宿主在装配时
构造本目录下的适配器并注入（经 ``ToolContext`` / ``context`` 字典传递给工具，或经
构造器传递给 MemoryManager 等）。
"""
from novamind.features.agent.adapters.web_search_adapter import HostWebSearchPort
from novamind.features.agent.adapters.knowledge_search_adapter import (
    HostKnowledgeSearchPort,
)
from novamind.features.agent.adapters.memory_store_adapter import (
    HostMemorySearchPort,
    HostMemoryStorePort,
)
from novamind.features.agent.adapters.prompt_provider_adapter import HostPromptProvider

__all__ = [
    "HostWebSearchPort",
    "HostKnowledgeSearchPort",
    "HostMemoryStorePort",
    "HostMemorySearchPort",
    "HostPromptProvider",
]