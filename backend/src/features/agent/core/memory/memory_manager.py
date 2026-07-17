"""
MemoryManager — 记忆系统统一门面

编排长期记忆和短期记忆的完整生命周期。
每请求创建，通过 create() 工厂方法注入依赖。

生命周期:
  build_frozen_snapshot() → 长期记忆 → system prompt（会话级不变）
  prefetch(query)         → 语义搜索相关记忆 → 用户消息（每轮变化）
  build_context()         → DB 加载 + Token 预算 + 压缩 → MemorySnapshot
"""
from typing import Any, Callable, Dict, List, Optional

from novamind.features.agent.core.memory.interfaces import (
    LongTermMemoryEntry,
    MemorySnapshot,
)
from novamind.features.agent.core.memory.short_term import ShortTermMemory
from novamind.features.agent.core.memory.long_term import LongTermMemory
from novamind.features.agent.core.memory.token_budget import TokenBudget
from novamind.features.agent.core.memory.context_compressor import ContextCompressor
from novamind.features.agent.repository.memory_repository import MemoryRepository
from novamind.features.agent.repository.context_summary_repository import ContextSummaryRepository
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class MemoryManager:
    """记忆系统统一门面"""

    def __init__(
        self,
        short_term: ShortTermMemory,
        long_term: LongTermMemory,
        memory_repository: MemoryRepository,
        message_repository: Any,
        summary_repository: Optional[ContextSummaryRepository] = None,
    ):
        self._short_term = short_term
        self._long_term = long_term
        self._memory_repo = memory_repository
        self._msg_repo = message_repository
        self._summary_repo = summary_repository
        # 冻结快照缓存
        self._frozen_snapshot_cache: Dict[str, str] = {}

    @classmethod
    def create(
        cls,
        message_repository: Any,
        tool_call_repository: Any,
        session_repository: Any,
        memory_repository: MemoryRepository,
        model: str,
        llm_client_factory: Callable,
        memory_search_repo: Optional[Any] = None,
        embedding_factory: Optional[Callable] = None,
        todo_store: Optional[Any] = None,
        conversation_id: Optional[int] = None,
        agent_id: Optional[int] = None,
        user_id: Optional[int] = None,
        auxiliary_llm_factory: Optional[Callable] = None,
    ) -> "MemoryManager":
        """工厂方法：创建完整配置的 MemoryManager"""
        summary_repo = ContextSummaryRepository(memory_repository.session)

        # 先创建 LongTermMemory（ContextCompressor 需要访问）
        long_term = LongTermMemory(
            memory_repository,
            llm_client_factory,
            memory_search_repo=memory_search_repo,
            embedding_factory=embedding_factory,
        )

        # 压缩策略：ContextCompressor（五阶段结构化压缩 + 压缩时记忆提取）
        compression_strategy = ContextCompressor(
            llm_client_factory=llm_client_factory,
            summary_repository=summary_repo,
            todo_store=todo_store,
            conversation_id=conversation_id,
            long_term_memory=long_term,
            agent_id=agent_id,
            user_id=user_id,
            auxiliary_llm_factory=auxiliary_llm_factory,
        )

        short_term = ShortTermMemory(
            message_repository=message_repository,
            tool_call_repository=tool_call_repository,
            session_repository=session_repository,
            token_budget=TokenBudget(model),
            compression_strategy=compression_strategy,
            summary_repository=summary_repo,
        )
        return cls(
            short_term=short_term,
            long_term=long_term,
            memory_repository=memory_repository,
            message_repository=message_repository,
            summary_repository=summary_repo,
        )

    # ==================== 长期记忆 ====================

    async def build_frozen_snapshot(self, agent_id: int, user_id: int) -> str:
        """构建冻结快照：首次从 MySQL 加载后缓存到内存，会话期间不再查询 DB。

        真正的冻结：即使 consolidate 写入新记忆，当前会话的快照也不变。
        新记忆在下一个会话的首次 build_frozen_snapshot 时才可见。
        """
        cache_key = f"{agent_id}:{user_id}"
        if cache_key in self._frozen_snapshot_cache:
            return self._frozen_snapshot_cache[cache_key]

        try:
            memories, _ = await self._memory_repo.list_by_agent(
                agent_id, user_id, limit=20
            )
            if not memories:
                self._frozen_snapshot_cache[cache_key] = ""
                return ""

            lines = [f"- [{m.category}] {m.content}" for m in memories]
            snapshot = "## 关于该用户的长期记忆\n" + "\n".join(lines)

            # 冻结：缓存到内存，会话期间不再更新
            self._frozen_snapshot_cache[cache_key] = snapshot
            return snapshot
        except Exception as e:
            logger.warning("冻结快照加载失败", error=str(e))
            return ""

    async def prefetch(
        self,
        query: str,
        agent_id: int,
        user_id: int,
        top_k: int = 3,
    ) -> List[LongTermMemoryEntry]:
        """动态预取相关记忆（Phase 1: MySQL LIKE，Phase 2 添加 ES）"""
        try:
            return await self._long_term.search(
                agent_id=agent_id,
                user_id=user_id,
                query=query,
                top_k=top_k,
            )
        except Exception as e:
            logger.warning("长期记忆预取失败", error=str(e))
            return []

    # ==================== 短期记忆 ====================

    async def build_context(
        self,
        system_prompt: str,
        conversation_id: int,
        max_tokens: int,
    ) -> MemorySnapshot:
        """构建发送给 LLM 的完整上下文快照"""
        return await self._short_term.build_context(
            system_prompt=system_prompt,
            conversation_id=conversation_id,
            max_tokens=max_tokens,
        )
