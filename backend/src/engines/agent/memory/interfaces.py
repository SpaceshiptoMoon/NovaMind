"""
记忆系统抽象接口和数据模型，定义 IShortTermMemory 和 ILongTermMemory 契约。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from novamind.engines.agent.context_types import LongTermMemoryEntry  # noqa: F401

# ==================== 数据模型 ====================

@dataclass
class MemoryMessage:
    """统一的内部消息模型"""

    role: str  # user / assistant / system / tool
    content: str | list[dict[str, Any]]
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    token_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemorySnapshot:
    """
    记忆快照：发送给 LLM 的完整上下文

    由 ShortTermMemory.build_context() 产出，
    AgentEngine 消费 snapshot.messages 构建请求。
    """

    messages: list[dict[str, Any]]  # OpenAI 格式消息列表
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
        tools: list[dict[str, Any]] | None = None,
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
        """添加一条消息到短期记忆。

        Args:
            conversation_id: 会话 ID。
            message: 统一消息模型实例。
        """
        ...

    @abstractmethod
    async def get_token_count(self, conversation_id: int) -> int:
        """获取当前对话的 token 估计值。

        Args:
            conversation_id: 会话 ID。

        Returns:
            该会话消息的 token 估计值。
        """
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
        source_conversation_id: int | None = None,
    ) -> LongTermMemoryEntry:
        """存储一条长期记忆。

        Args:
            agent_id: Agent ID。
            user_id: 用户 ID。
            category: 记忆类别（preference/fact/procedure/insight）。
            content: 记忆正文。
            source_conversation_id: 来源会话 ID，可空。

        Returns:
            新建的记忆条目。
        """
        ...

    @abstractmethod
    async def search(
        self,
        agent_id: int,
        user_id: int,
        query: str,
        top_k: int = 5,
        categories: list[str] | None = None,
    ) -> list[LongTermMemoryEntry]:
        """根据查询搜索相关的长期记忆。

        Args:
            agent_id: Agent ID。
            user_id: 用户 ID。
            query: 检索查询文本。
            top_k: 返回条数上限。
            categories: 限定类别列表，None 不限。

        Returns:
            按相关度排序的记忆条目列表。
        """
        ...

    @abstractmethod
    async def consolidate(
        self,
        agent_id: int,
        user_id: int,
        conversation_id: int,
        messages: list[MemoryMessage],
    ) -> int:
        """
        从对话消息中提取并存储有价值的长期记忆

        Returns:
            新存储的记忆条目数量
        """
        ...


# ==================== 存储端口（实现归业务，数据库引擎是业务的事） ====================

class IMemoryStore(ABC):
    """
    长期记忆存储端口：记忆条目与压缩摘要的增删改查。

    引擎只定义契约——具体存哪个数据库（MySQL/PG/向量库）由业务侧实现并
    注入。方法集即引擎消费面（LongTermMemory/ContextCompressor 实际调用）。
    """

    @abstractmethod
    async def create(self, agent_id: int, user_id: int, category: str,
                     content: str, source_conversation_id: int | None = None) -> LongTermMemoryEntry:
        """新建一条长期记忆，返回含主键的完整条目。"""
        ...

    @abstractmethod
    async def find_similar(self, agent_id: int, content: str, limit: int = 5) -> list[LongTermMemoryEntry]:
        """按内容相似度（LIKE/向量由实现决定）找近邻记忆，供去重合并判定。"""
        ...

    @abstractmethod
    async def list_by_agent(self, agent_id: int, limit: int = 100) -> list[LongTermMemoryEntry]:
        """列出某 Agent 的记忆条目。"""
        ...

    @abstractmethod
    async def get_by_id(self, memory_id: int) -> LongTermMemoryEntry | None:
        """按主键取记忆条目；不存在返回 None。"""
        ...

    @abstractmethod
    async def increment_access_count(self, memory_id: int) -> None:
        """命中计数 +1（检索命中/注入上下文时调用）。"""
        ...

    @abstractmethod
    async def update_content(self, memory_id: int, content: str) -> None:
        """更新记忆正文（合并/调和写回）。"""
        ...

    @abstractmethod
    async def update_extra_data(self, memory_id: int, extra_data: dict) -> None:
        """更新扩展数据列（如 mem0_id 锚点）。"""
        ...

    @abstractmethod
    async def delete(self, memory_id: int) -> bool:
        """删除记忆条目；返回是否实际删除。"""
        ...

    @abstractmethod
    async def search_by_keywords(self, agent_id: int, keywords: list[str],
                                 limit: int = 20) -> list[LongTermMemoryEntry]:
        """按关键词集过滤记忆（实现决定匹配语义）。"""
        ...

    @abstractmethod
    async def find_by_content_contains(self, agent_id: int, text: str,
                                       limit: int = 20) -> list[LongTermMemoryEntry]:
        """按正文包含文本过滤记忆。"""
        ...

    @abstractmethod
    async def flush(self) -> None:
        """把会话内挂起的写入刷出（实现自行决定事务边界）。"""
        ...

    @abstractmethod
    async def save_summary(self, agent_id: int, conversation_id: int | None, summary: Any) -> None:
        """保存压缩摘要条目。"""
        ...

    @abstractmethod
    async def get_latest_summary(self, agent_id: int, conversation_id: int | None = None) -> Any:
        """取最近一条压缩摘要；无则 None。"""
        ...


class IMemorySearch(ABC):
    """长期记忆向量检索端口（ES 索引由实现方管理）。"""

    @abstractmethod
    async def ensure_index(self, agent_id: int) -> None:
        """确保该 Agent 的记忆索引存在（维度自愈由实现负责）。"""
        ...

    @abstractmethod
    async def index_memory(self, agent_id: int, memory_id: int, user_id: int, category: str,
                           content: str, embedding: list[float],
                           source_type: str = "consolidate",
                           source_conversation_id: int | None = None,
                           created_at: Any = None) -> bool:
        """索引单条记忆向量；返回 True 表示索引因维度不匹配被重建（调用方应全量重索引）。"""
        ...

    @abstractmethod
    async def search(self, agent_id: int, query_embedding: list[float],
                     top_k: int = 5, categories: list[str] | None = None) -> list[LongTermMemoryEntry]:
        """按向量相似度检索记忆条目。"""
        ...

    @abstractmethod
    async def delete_memory(self, agent_id: int, memory_id: int) -> None:
        """从索引删除单条记忆文档。"""
        ...

