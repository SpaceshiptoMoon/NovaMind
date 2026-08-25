"""
记忆系统抽象接口和数据模型，定义 IShortTermMemory 和 ILongTermMemory 契约。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from novamind.engines.agent.ports import LongTermMemoryEntry  # noqa: F401


# ==================== 数据模型 ====================

@dataclass
class MemoryMessage:
    """统一的内部消息模型"""

    role: str  # user / assistant / system / tool
    content: Union[str, List[Dict[str, Any]]]
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    token_count: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemorySnapshot:
    """
    记忆快照：发送给 LLM 的完整上下文

    由 ShortTermMemory.build_context() 产出，
    AgentEngine 消费 snapshot.messages 构建请求。
    """

    messages: List[Dict[str, Any]]  # OpenAI 格式消息列表
    total_tokens: int
    compressed: bool = False
    compression_ratio: float = 1.0
    # ContextMeter 三项分项（total_tokens = system + tools + messages）
    system_tokens: int = 0
    tools_tokens: int = 0
    messages_tokens: int = 0
    # 压缩元数据（compressed=True 时填充，供前端 CompactionItem 显示「已压缩 N 条」+ 摘要正文）
    compressed_count: int = 0
    compaction_summary: str = ""
    # 窗口口径，供前端直接用
    context_window: int = 0
    reserved_tokens: int = 0


# ==================== 抽象接口 ====================

class IShortTermMemory(ABC):
    """
    短期记忆接口：管理当前对话的上下文窗口

    核心职责：
    1. 从数据库加载消息并格式化为 OpenAI messages
    2. Token 预算管理（根据模型窗口大小决定保留哪些消息）
    3. 超限时自动触发压缩策略
    """

    @abstractmethod
    async def build_context(
        self,
        system_prompt: str,
        conversation_id: int,
        max_tokens: int,
        reserve_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        dry_run: bool = False,
    ) -> MemorySnapshot:
        """
        构建发送给 LLM 的完整上下文快照

        Args:
            system_prompt: 系统提示词
            conversation_id: 会话 ID
            max_tokens: 模型上下文窗口大小（token 数）
            reserve_tokens: 为 LLM 生成预留的 token 数
            tools: OpenAI tools schema 列表，用于计算 tools 项 token（ContextMeter 分项）
            dry_run: True 时只算 token 不触发压缩、不写 summary（用于历史会话初始用量估算）

        Returns:
            MemorySnapshot 包含格式化后的消息列表和 token 统计
        """
        ...

    @abstractmethod
    async def add_message(
        self, conversation_id: int, message: MemoryMessage
    ) -> None:
        """添加一条消息到短期记忆"""
        ...

    @abstractmethod
    async def get_token_count(self, conversation_id: int) -> int:
        """获取当前对话的 token 估计值"""
        ...


class ILongTermMemory(ABC):
    """
    长期记忆接口：跨会话的知识/偏好记忆

    核心职责：
    1. 存储从对话中提取的关键信息（偏好、事实、流程、洞察）
    2. 对话开始时搜索相关的历史记忆注入上下文
    3. 对话结束时自动巩固有价值的信息
    """

    @abstractmethod
    async def store(
        self,
        agent_id: int,
        user_id: int,
        category: str,
        content: str,
        source_conversation_id: Optional[int] = None,
    ) -> LongTermMemoryEntry:
        """存储一条长期记忆"""
        ...

    @abstractmethod
    async def search(
        self,
        agent_id: int,
        user_id: int,
        query: str,
        top_k: int = 5,
        categories: Optional[List[str]] = None,
    ) -> List[LongTermMemoryEntry]:
        """根据查询搜索相关的长期记忆"""
        ...

    @abstractmethod
    async def consolidate(
        self,
        agent_id: int,
        user_id: int,
        conversation_id: int,
        messages: List[MemoryMessage],
    ) -> int:
        """
        从对话消息中提取并存储有价值的长期记忆

        Returns:
            新存储的记忆条目数量
        """
        ...

