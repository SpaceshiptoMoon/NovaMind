"""
Agent 引擎宿主适配层，实现引擎端口协议，桥接宿主 ORM / 配置 / 外部服务。
"""
from novamind.features.agent.adapters.attachment_read_adapter import (
    HostAttachmentReadPort,
)
from novamind.features.agent.adapters.knowledge_search_adapter import (
    HostKnowledgeSearchPort,
)
from novamind.features.agent.adapters.memory_store_adapter import (
    HostMemorySearchPort,
    HostMemoryStorePort,
)

__all__ = [
    "HostKnowledgeSearchPort",
    "HostMemoryStorePort",
    "HostMemorySearchPort",
    "HostAttachmentReadPort",
]
