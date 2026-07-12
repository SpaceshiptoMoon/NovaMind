"""
Agent 记忆系统

两层记忆架构：
- 短期记忆（ShortTermMemory）：当前对话上下文，Token 预算管理，自动压缩
- 长期记忆（LongTermMemory）：跨会话的知识/偏好/经验，对话结束时巩固

统一门面：MemoryManager 编排记忆的完整生命周期
"""
from novamind.features.agent.core.memory.memory_manager import MemoryManager

__all__ = ["MemoryManager"]
