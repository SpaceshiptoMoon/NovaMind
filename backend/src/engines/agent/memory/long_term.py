"""
长期记忆管理器，提取、去重、持久化对话中的关键信息，搜索相关记忆注入上下文。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from novamind.engines.agent.memory.interfaces import (
    ILongTermMemory,
    IMemorySearch,
    IMemoryStore,
    LongTermMemoryEntry,
    MemoryMessage,
)
from novamind.shared.logging import get_logger
from novamind.shared.prompts.prompt_manager import PromptManager

logger = get_logger(__name__)


class LongTermMemory(ILongTermMemory):
    """
    长期记忆管理器

    记忆提取流程（consolidate）：
    1. 筛选包含有价值信息的对话段
    2. 使用 LLM 提取结构化记忆
    3. 与已有记忆去重比对
    4. 存入 agent_memories 表
    5. 生成 embedding → ES 索引

    记忆检索流程（search）：
    1. 优先 ES hybrid search（向量 + BM25）
    2. ES 不可用时降级到 MySQL LIKE
    """

    def __init__(
        self,
        memory_store: IMemoryStore,
        llm_client_factory: Callable,
        prompt_provider: PromptManager,
        memory_search: IMemorySearch | None = None,
        embedding_factory: Callable | None = None,
        reconciler: Any | None = None,
    ):
        """注入记忆存储、LLM 工厂与 prompt 提供者；搜索与 embedding 端口可选，缺省时分别降级 MySQL LIKE 与跳过向量化。reconciler 提供时 consolidate 走 Mem0 调和管线，失败降级内置提取。"""
        self._store = memory_store
        self._llm_factory = llm_client_factory
        self._prompt_provider = prompt_provider
        self._search = memory_search
        self._embedding_factory = embedding_factory
        self._reconciler = reconciler

    async def store(
        self,
        agent_id: int,
        user_id: int,
        category: str,
        content: str,
        source_conversation_id: int | None = None,
        source_type: str = "consolidate",
    ) -> LongTermMemoryEntry:
        """存储一条长期记忆 → MySQL + ES。

        Args:
            agent_id: Agent ID。
            user_id: 用户 ID。
            category: 记忆类别（preference/fact/procedure/insight）。
            content: 记忆正文。
            source_conversation_id: 来源会话 ID，可空。
            source_type: 来源标记（consolidate/manual 等）。

        Returns:
            新建的记忆条目（已异步索引到 ES）。

        Raises:
            ValueError: 内容未通过安全扫描。
        """
        # 安全扫描
        from novamind.engines.agent.memory.security import scan_memory_content
        scan = scan_memory_content(content)
        if not scan:
            logger.warning("记忆写入被安全扫描拦截", threats=scan.threats, category=category)
            raise ValueError(f"记忆内容未通过安全检查: {scan.threats}")

        entry = await self._store.create(
            agent_id=agent_id,
            user_id=user_id,
            category=category,
            content=content,
            source_conversation_id=source_conversation_id,
            source_type=source_type,
        )
        logger.info(
            "长期记忆已存储",
            agent_id=agent_id,
            category=category,
            memory_id=entry.id,
        )

        # 异步索引到 ES
        await self._index_to_es(agent_id, entry, source_type)

        return entry

    async def replace(
        self,
        agent_id: int,
        user_id: int,
        category: str,
        old_content: str,
        new_content: str,
    ) -> dict[str, Any]:
        """替换记忆内容（子串匹配）。

        Args:
            agent_id: Agent ID。
            user_id: 用户 ID。
            category: 记忆类别。
            old_content: 用于定位的记忆内容子串。
            new_content: 替换后的新内容。

        Returns:
            成功为 {message, id}；未匹配或安全扫描未过为 {error}。
        """
        from novamind.engines.agent.memory.security import scan_memory_content

        scan = scan_memory_content(new_content)
        if not scan:
            return {"error": f"新内容未通过安全检查: {scan.threats}"}

        entry = await self._store.find_by_content_contains(agent_id, user_id, old_content)
        if not entry:
            return {"error": "未找到匹配的记忆"}

        await self._store.update_content(entry.id, new_content)
        await self._store.flush()
        return {"message": "记忆已更新", "id": entry.id}

    async def remove(
        self,
        agent_id: int,
        user_id: int,
        old_content: str,
    ) -> dict[str, Any]:
        """移除记忆（子串匹配）。

        Args:
            agent_id: Agent ID。
            user_id: 用户 ID。
            old_content: 用于定位的记忆内容子串。

        Returns:
            成功为 {message, id}；未匹配为 {error}（ES 删除失败仅告警不报错）。
        """
        entry = await self._store.find_by_content_contains(agent_id, user_id, old_content)
        if not entry:
            return {"error": "未找到匹配的记忆"}

        await self._store.delete(entry.id)
        await self._store.flush()

        try:
            if self._search:
                await self._search.delete_memory(agent_id, entry.id)
        except Exception as e:
            logger.warning("ES 记忆删除失败", error=str(e))

        return {"message": "记忆已移除", "id": entry.id}

    async def search(
        self,
        agent_id: int,
        user_id: int,
        query: str,
        top_k: int = 5,
        categories: list[str] | None = None,
        count_access: bool = True,
    ) -> list[LongTermMemoryEntry]:
        """根据查询搜索相关的长期记忆：ES hybrid → MySQL LIKE。

        Args:
            agent_id: Agent ID。
            user_id: 用户 ID。
            query: 检索查询文本。
            top_k: 返回条数上限。
            categories: 限定类别列表，None 不限。
            count_access: 是否递增命中记忆的访问计数（access_count 是用户侧
                召回热度指标；dry_run 估算等机器内部调用传 False）。

        Returns:
            按相关度排序的记忆条目；ES 不可用或无结果时降级 MySQL LIKE。
        """
        # 优先 ES 搜索
        if self._search and self._embedding_factory:
            es_results = await self._search_es(
                agent_id, user_id, query, top_k, categories, count_access=count_access
            )
            if es_results:
                return es_results

        # 降级到 MySQL LIKE
        return await self._search_mysql(
            agent_id, user_id, query, top_k, categories, count_access=count_access
        )

    async def consolidate(
        self,
        agent_id: int,
        user_id: int,
        conversation_id: int,
        messages: list[MemoryMessage],
        min_turns: int = 5,
        max_recent_turns: int = 10,
    ) -> int:
        """从对话消息中提取并存储有价值的长期记忆。

        配置了 Mem0 reconciler 时走 Mem0 提取+语义调和管线；任何失败降级内置
        提取路径（_consolidate_builtin）。两类路径共享轮次门禁与消息预算。

        Returns:
            新存储/调和应用的记忆条目数量。
        """
        if not messages:
            return 0

        # 按 user 角色消息数计算实际对话轮次
        user_turns = sum(1 for m in messages if m.role == "user")
        if user_turns < min_turns:
            logger.debug(
                "跳过巩固：对话轮次不足",
                user_turns=user_turns,
                min_turns=min_turns,
            )
            return 0

        if self._reconciler is not None:
            try:
                applied = await self._reconciler.reconcile(
                    agent_id=agent_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    messages=messages,
                )
                logger.info(
                    "Mem0 记忆调和完成",
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    applied=applied,
                )
                return applied
            except Exception as e:
                logger.warning(
                    "Mem0 调和失败，降级内置提取", error=str(e)
                )

        return await self._consolidate_builtin(
            agent_id, user_id, conversation_id, messages, max_recent_turns
        )

    async def _consolidate_builtin(
        self,
        agent_id: int,
        user_id: int,
        conversation_id: int,
        messages: list[MemoryMessage],
        max_recent_turns: int = 10,
    ) -> int:
        """内置提取路径：LLM 提取结构化记忆 → 精确匹配去重 → store。"""
        extraction_prompt = self._build_extraction_prompt(
            messages, max_recent_turns=max_recent_turns, max_prompt_tokens=3000
        )
        try:
            llm = await self._llm_factory()
            result = await llm.generate_text(
                prompt=extraction_prompt,
                max_tokens=1024,
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            extracted = self._parse_extraction_result(result)
            stored_count = 0

            for item in extracted:
                existing = await self._store.find_similar(
                    agent_id=agent_id,
                    user_id=user_id,
                    category=item["category"],
                    content=item["content"],
                )
                if not existing:
                    try:
                        await self.store(
                            agent_id=agent_id,
                            user_id=user_id,
                            category=item["category"],
                            content=item["content"],
                            source_conversation_id=conversation_id,
                            source_type="consolidate",
                        )
                        stored_count += 1
                    except ValueError:
                        # 安全扫描拦截，跳过该条
                        continue

            logger.info(
                "记忆巩固完成",
                agent_id=agent_id,
                conversation_id=conversation_id,
                extracted=len(extracted),
                stored=stored_count,
            )
            return stored_count

        except Exception as e:
            logger.warning("记忆巩固失败", error=str(e))
            return 0

    # ==================== ES 操作 ====================

    async def _index_to_es(
        self, agent_id: int, entry: LongTermMemoryEntry, source_type: str
    ) -> None:
        """生成 embedding 并索引到 ES。

        若 index_memory 返回重建标志（embedding 模型维度变更导致索引自愈重建），
        从 MySQL 重索引该 Agent 全部记忆，恢复向量检索能力。
        """
        if not self._search or not self._embedding_factory:
            return
        try:
            embedding_client = await self._embedding_factory()
            embedding = await embedding_client.generate_embedding(entry.content)
            if not embedding:
                return
            recreated = await self._search.index_memory(
                agent_id=agent_id,
                memory_id=entry.id,
                user_id=entry.user_id,
                category=entry.category,
                content=entry.content,
                embedding=embedding,
                source_type=source_type,
                source_conversation_id=entry.source_conversation_id,
                created_at=entry.created_at,
            )
            if recreated:
                await self._reindex_all_memories(agent_id, entry.user_id, embedding_client)
        except Exception as e:
            logger.warning("ES 记忆索引失败", memory_id=entry.id, error=str(e))

    async def _reindex_all_memories(
        self,
        agent_id: int,
        user_id: int,
        embedding_client: Any,
        batch_size: int = 100,
        max_total: int = 1000,
    ) -> None:
        """重建索引后从 MySQL source-of-truth 重嵌全部记忆。

        分页拉取 list_by_agent，逐条生成 embedding 并 index_memory。
        失败不阻断（仅 warning）。max_total 兜底防异常巨量记忆拖垮会话。
        """
        if not self._search:
            return
        try:
            reindexed = 0
            offset = 0
            while reindexed < max_total:
                memories, total = await self._store.list_by_agent(
                    agent_id=agent_id, user_id=user_id, limit=batch_size, offset=offset,
                )
                if not memories:
                    break
                for m in memories:
                    if reindexed >= max_total:
                        break
                    try:
                        emb = await embedding_client.generate_embedding(m.content)
                        if not emb:
                            continue
                        await self._search.index_memory(
                            agent_id=agent_id,
                            memory_id=m.id,
                            user_id=m.user_id,
                            category=m.category,
                            content=m.content,
                            embedding=emb,
                            source_type="consolidate",
                            source_conversation_id=m.source_conversation_id,
                            created_at=m.created_at,
                        )
                        reindexed += 1
                    except Exception as e:
                        logger.warning("重索引单条记忆失败", memory_id=m.id, error=str(e))
                if reindexed >= total or len(memories) < batch_size:
                    break
                offset += batch_size
            logger.info("记忆重建后重索引完成", agent_id=agent_id, reindexed=reindexed)
        except Exception as e:
            logger.warning("记忆全量重索引失败", agent_id=agent_id, error=str(e))

    async def _search_es(
        self,
        agent_id: int,
        user_id: int,
        query: str,
        top_k: int,
        categories: list[str] | None,
        count_access: bool = True,
    ) -> list[LongTermMemoryEntry]:
        """ES hybrid 搜索 → 回填 MySQL 完整数据"""
        try:
            embedding_client = await self._embedding_factory()
            query_vector = await embedding_client.generate_embedding(query)
            if not query_vector:
                return []

            results = await self._search.search(
                agent_id=agent_id,
                query_vector=query_vector,
                query_text=query,
                top_k=top_k,
                user_id=user_id,
                categories=categories,
            )
            if not results:
                return []

            # 从 MySQL 回填完整数据 + 递增访问计数
            entries: list[LongTermMemoryEntry] = []
            for r in results:
                memory = await self._store.get_by_id(r["memory_id"])
                if memory:
                    if count_access:
                        await self._store.increment_access_count(memory.id)
                    entries.append(
                        LongTermMemoryEntry(
                            id=memory.id,
                            agent_id=memory.agent_id,
                            user_id=memory.user_id,
                            category=memory.category,
                            content=memory.content,
                            relevance_score=r.get("score", 0.0),
                            access_count=memory.access_count,
                            source_conversation_id=memory.source_conversation_id,
                            created_at=memory.created_at,
                            updated_at=memory.updated_at,
                        )
                    )
            return entries
        except Exception as e:
            logger.warning("ES 搜索失败，降级到 MySQL", error=str(e))
            return []

    async def _search_mysql(
        self,
        agent_id: int,
        user_id: int,
        query: str,
        top_k: int,
        categories: list[str] | None,
        count_access: bool = True,
    ) -> list[LongTermMemoryEntry]:
        """MySQL LIKE fallback"""
        memories = await self._store.search_by_keywords(
            agent_id=agent_id,
            user_id=user_id,
            query=query,
            top_k=top_k,
            categories=categories,
        )
        entries = []
        for m in memories:
            if count_access:
                await self._store.increment_access_count(m.id)
            entries.append(
                LongTermMemoryEntry(
                    id=m.id,
                    agent_id=m.agent_id,
                    user_id=m.user_id,
                    category=m.category,
                    content=m.content,
                    relevance_score=m.relevance_score,
                    access_count=m.access_count,
                    source_conversation_id=m.source_conversation_id,
                    created_at=m.created_at,
                    updated_at=m.updated_at,
                )
            )
        return entries

    # ==================== Prompt 构建 ====================

    def _build_extraction_prompt(
        self,
        messages: list[MemoryMessage],
        max_recent_turns: int = 10,
        max_prompt_tokens: int = 3000,
    ) -> str:
        """构建记忆提取 prompt（含 Token 上限保护）"""
        filtered = [m for m in messages if m.role != "system"]
        filtered = filtered[-max_recent_turns:]

        conversation_text = ""
        for m in filtered:
            if not m.content:
                continue
            if m.role == "user":
                conversation_text += f"用户: {m.content}\n"
            elif m.role == "assistant":
                text = m.content[:300] + ("..." if len(m.content) > 300 else "")
                conversation_text += f"助手: {text}\n"
            elif m.role == "tool":
                text = m.content[:200] + ("..." if len(m.content) > 200 else "")
                conversation_text += f"[工具{m.tool_name}]: {text}\n"

        # Token 上限保护
        max_chars = max_prompt_tokens * 2
        if len(conversation_text) > max_chars:
            conversation_text = "..." + conversation_text[-max_chars:]

        return self._prompt_provider.format(
            "agent_long_term_memory",
            conversation_text=conversation_text,
        )

    def _parse_extraction_result(self, result: str) -> list[dict]:
        """解析 LLM 提取结果，兼容多种 JSON 格式"""
        from novamind.shared.utils.llm_response import extract_json_value

        valid_categories = {"preference", "fact", "procedure", "insight"}

        parsed = extract_json_value(result)
        if parsed is None:
            logger.warning("记忆提取结果 JSON 解析失败", result=result[:200])
            return []

        if not isinstance(parsed, list):
            return []

        valid_items = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            category = item.get("category", "")
            content = item.get("content", "")
            if category in valid_categories and content and len(content.strip()) > 0:
                valid_items.append({
                    "category": category,
                    "content": content.strip(),
                })

        return valid_items