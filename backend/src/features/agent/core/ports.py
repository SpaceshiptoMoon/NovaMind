"""Agent 引擎端口 re-export 壳（向后兼容）

中立端口与 DTO 已上提到 ``shared/agent_ports.py``（供 engines 与 features 双向 import），
本模块仅做 re-export，保持 ``from novamind.features.agent.core import ports`` /
``from novamind.features.agent.core.ports import X`` 现有导入路径零改动。

迁移过渡期保留；``engines/agent/`` 落地后，host 侧与测试改 import ``novamind.shared.agent_ports``，
本壳随之删除（见 batch 5 清理）。
"""
from novamind.shared.agent_ports import (  # noqa: F401
    ContextSummaryEntry,
    DocumentInfo,
    DocumentListResult,
    KbInfo,
    KnowledgeSearchItem,
    KnowledgeSearchPort,
    LongTermMemoryEntry,
    MemorySearchPort,
    MemoryStorePort,
    SpaceInfo,
    WebSearchPort,
    WebSearchResult,
)

__all__ = [
    "WebSearchResult",
    "WebSearchPort",
    "SpaceInfo",
    "KbInfo",
    "KnowledgeSearchItem",
    "DocumentInfo",
    "DocumentListResult",
    "KnowledgeSearchPort",
    "ContextSummaryEntry",
    "LongTermMemoryEntry",
    "MemoryStorePort",
    "MemorySearchPort",
]