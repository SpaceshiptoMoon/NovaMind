"""
MemoryManager — 记忆系统统一门面，编排长期记忆和短期记忆的生命周期。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 宿主类仅注解用（TYPE_CHECKING 防 import 环）
    from novamind.features.agent.services.host_memory_store import (
        HostMemorySearchPort,
        HostMemoryStorePort,
    )
from collections.abc import Callable
from typing import Any

from novamind.engines.agent.memory.context_compressor import ContextCompressor
from novamind.engines.agent.memory.interfaces import (
    LongTermMemoryEntry,
    MemorySnapshot,
)
from novamind.engines.agent.memory.long_term import LongTermMemory
from novamind.engines.agent.memory.short_term import ShortTermMemory
from novamind.engines.agent.memory.token_budget import TokenBudget
from novamind.shared.logging import get_logger
from novamind.shared.prompts.prompt_manager import PromptManager

logger = get_logger(__name__)


class MemoryManager:
    """记忆系统统一门面"""

    def __init__(
        self,
        short_term: ShortTermMemory,
        long_term: LongTermMemory,
        long_term_store: HostMemoryStorePort,
        summary_store: HostMemoryStorePort,
        message_repository: Any,
    ):
        """组装短期/长期记忆与消息仓储；冻结快照缓存避免同会话重复构建快照。"""
        self._short_term = short_term
        self._long_term = long_term
        self._long_term_store = long_term_store
        self._summary_store = summary_store
        self._msg_repo = message_repository
        # 冻结快照缓存
        self._frozen_snapshot_cache: dict[str, str] = {}

    @classmethod
    def create(
        cls,
        message_repository: Any,
        tool_call_repository: Any,
        session_repository: Any,
        long_term_store: HostMemoryStorePort,
        summary_store: HostMemoryStorePort,
        prompt_provider: PromptManager,
        model: str,
        llm_client_factory: Callable,
        memory_search: HostMemorySearchPort | None = None,
        embedding_factory: Callable | None = None,
        todo_store: Any | None = None,
        conversation_id: int | None = None,
        agent_id: int | None = None,
        user_id: int | None = None,
        auxiliary_llm_factory: Callable | None = None,
    ) -> MemoryManager:
        """工厂方法：创建完整配置的 MemoryManager。

        Args:
            message_repository: 消息仓储。
            tool_call_repository: 工具调用仓储。
            session_repository: 会话仓储。
            long_term_store: 长期记忆存储端口。
            summary_store: 压缩摘要存储端口。
            prompt_provider: prompt 提供者。
            model: 模型名，决定 token 计数口径。
            llm_client_factory: LLM 客户端工厂。
            memory_search: ES 记忆搜索端口，可空。
            embedding_factory: embedding 客户端工厂，可空。
            todo_store: 压缩后任务存储，可空。
            conversation_id: 当前会话 ID，可空。
            agent_id: Agent ID，可空。
            user_id: 用户 ID，可空。
            auxiliary_llm_factory: 压缩用辅助 LLM 工厂，可空。

        Returns:
            组装完成的 MemoryManager 实例。
        """
        # 先创建 LongTermMemory（ContextCompressor 需要访问）
        long_term = LongTermMemory(
            long_term_store,
            llm_client_factory,
            prompt_provider=prompt_provider,
            memory_search=memory_search,
            embedding_factory=embedding_factory,
        )

        # 压缩策略：ContextCompressor（五阶段结构化压缩 + 压缩时记忆提取）
        compression_strategy = ContextCompressor(
            llm_client_factory=llm_client_factory,
            summary_store=summary_store,
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
            summary_store=summary_store,
        )
        return cls(
            short_term=short_term,
            long_term=long_term,
            long_term_store=long_term_store,
            summary_store=summary_store,
            message_repository=message_repository,
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
            memories, _ = await self._long_term_store.list_by_agent(
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
    ) -> list[LongTermMemoryEntry]:
        """动态预取相关记忆（Phase 1: MySQL LIKE，Phase 2 添加 ES）。

        Args:
            query: 查询文本。
            agent_id: Agent ID。
            user_id: 用户 ID。
            top_k: 返回条数上限。

        Returns:
            相关记忆条目列表；检索失败时为空列表。
        """
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
        tools: list[dict[str, Any]] | None = None,
        dry_run: bool = False,
    ) -> MemorySnapshot:
        """构建发送给 LLM 的完整上下文快照。

        Args:
            system_prompt: 系统提示词。
            conversation_id: 会话 ID。
            max_tokens: 模型上下文窗口大小（非生成上限）。
            tools: OpenAI tools schema 列表（计入 tools 分项 token），可空。
            dry_run: True 时只算 token 不触发压缩、不写摘要。

        Returns:
            MemorySnapshot，含格式化消息列表与 token 统计。
        """
        return await self._short_term.build_context(
            system_prompt=system_prompt,
            conversation_id=conversation_id,
            max_tokens=max_tokens,
            tools=tools,
            dry_run=dry_run,
        )