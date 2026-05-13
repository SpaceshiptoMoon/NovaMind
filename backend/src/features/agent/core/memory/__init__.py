"""
Agent 记忆系统

三层记忆架构：
- 短期记忆（ShortTermMemory）：当前对话上下文，Token 预算管理，自动压缩
- 长期记忆（LongTermMemory）：跨会话的知识/偏好/经验，对话结束时巩固
- 工作记忆（WorkingMemory）：当前任务的中间状态，内存级 TTL 自动过期
"""
from src.features.agent.core.memory.legacy import ConversationMemory

__all__ = ["ConversationMemory"]
