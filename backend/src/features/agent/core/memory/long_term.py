"""
长期记忆管理器

对话结束时从消息中提取关键信息（偏好/事实/过程/洞察），
去重后持久化到 agent_memories 表，并索引到 ES。
对话开始时搜索相关记忆注入上下文。

搜索路径：ES hybrid（向量+BM25）→ ES BM25 fallback → MySQL LIKE fallback
"""
from typing import Any, Callable, Dict, List, Optional

from novamind.features.agent.core.memory.interfaces import (
    ILongTermMemory,
    LongTermMemoryEntry,
    MemoryMessage,
)
from novamind.features.agent.repository.memory_repository import MemoryRepository
from novamind.shared.prompts import PromptTemplate, PromptManager
from novamind.core.middleware.structured_logging import get_logger

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
        memory_repository: MemoryRepository,
        llm_client_factory: Callable,
        memory_search_repo: Optional[Any] = None,
        embedding_factory: Optional[Callable] = None,
    ):
        self._repo = memory_repository
        self._llm_factory = llm_client_factory
        self._search_repo = memory_search_repo
        self._embedding_factory = embedding_factory

    async def store(
        self,
        agent_id: int,
        user_id: int,
        category: str,
        content: str,
        source_conversation_id: Optional[int] = None,
        source_type: str = "consolidate",
    ) -> LongTermMemoryEntry:
        """存储一条长期记忆 → MySQL + ES"""
        # 安全扫描
        from novamind.features.agent.core.memory.security import scan_memory_content
        scan = scan_memory_content(content)
        if not scan:
            logger.warning("记忆写入被安全扫描拦截", threats=scan.threats, category=category)
            raise ValueError(f"记忆内容未通过安全检查: {scan.threats}")

        memory = await self._repo.create(
            agent_id=agent_id,
            user_id=user_id,
            category=category,
            content=content,
            source_conversation_id=source_conversation_id,
            source_type=source_type,
        )
        entry = LongTermMemoryEntry(
            id=memory.id,
            agent_id=memory.agent_id,
            user_id=memory.user_id,
            category=memory.category,
            content=memory.content,
            source_type=memory.source_type or "consolidate",
            relevance_score=memory.relevance_score,
            access_count=memory.access_count,
            source_conversation_id=memory.source_conversation_id,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )
        logger.info(
            "长期记忆已存储",
            agent_id=agent_id,
            category=category,
            memory_id=memory.id,
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
    ) -> Dict[str, Any]:
        """替换记忆内容（子串匹配）"""
        from novamind.features.agent.core.memory.security import scan_memory_content

        scan = scan_memory_content(new_content)
        if not scan:
            return {"error": f"新内容未通过安全检查: {scan.threats}"}

        from novamind.features.agent.models.memory import AgentMemory
        from sqlalchemy import select

        stmt = select(AgentMemory).where(
            AgentMemory.agent_id == agent_id,
            AgentMemory.user_id == user_id,
            AgentMemory.content.contains(old_content),
        )
        result = await self._repo.session.execute(stmt)
        memory = result.scalar_one_or_none()
        if not memory:
            return {"error": "未找到匹配的记忆"}

        await self._repo.update(memory.id, content=new_content)
        await self._repo.session.flush()
        return {"message": "记忆已更新", "id": memory.id}

    async def remove(
        self,
        agent_id: int,
        user_id: int,
        old_content: str,
    ) -> Dict[str, Any]:
        """移除记忆（子串匹配）"""
        from novamind.features.agent.models.memory import AgentMemory
        from sqlalchemy import select

        stmt = select(AgentMemory).where(
            AgentMemory.agent_id == agent_id,
            AgentMemory.user_id == user_id,
            AgentMemory.content.contains(old_content),
        )
        result = await self._repo.session.execute(stmt)
        memory = result.scalar_one_or_none()
        if not memory:
            return {"error": "未找到匹配的记忆"}

        await self._repo.delete(memory.id)
        await self._repo.session.flush()

        try:
            if self._search_repo:
                await self._search_repo.delete_memory(agent_id, memory.id)
        except Exception as e:
            logger.warning("ES 记忆删除失败", error=str(e))

        return {"message": "记忆已移除", "id": memory.id}

    async def search(
        self,
        agent_id: int,
        user_id: int,
        query: str,
        top_k: int = 5,
        categories: Optional[List[str]] = None,
    ) -> List[LongTermMemoryEntry]:
        """根据查询搜索相关的长期记忆：ES hybrid → MySQL LIKE"""
        # 优先 ES 搜索
        if self._search_repo and self._embedding_factory:
            es_results = await self._search_es(
                agent_id, user_id, query, top_k, categories
            )
            if es_results:
                return es_results

        # 降级到 MySQL LIKE
        return await self._search_mysql(agent_id, user_id, query, top_k, categories)

    async def consolidate(
        self,
        agent_id: int,
        user_id: int,
        conversation_id: int,
        messages: List[MemoryMessage],
        min_turns: int = 5,
        max_recent_turns: int = 10,
    ) -> int:
        """
        从对话消息中提取并存储有价值的长期记忆

        步骤：
        0. 轮次检查：低于 min_turns 则跳过
        1. 预筛选：只取最近 N 轮消息
        2. 构建提取 prompt（含 Token 上限保护）
        3. 调用 LLM 提取结构化记忆（JSON 格式）
        4. 解析提取结果
        5. 逐条去重检查后存入数据库
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

        extraction_prompt = self._build_extraction_prompt(
            messages, max_recent_turns=max_recent_turns, max_prompt_tokens=3000
        )
        try:
            llm = await self._llm_factory()
            result = await llm.generate_text(
                prompt=extraction_prompt,
                max_tokens=1024,
                temperature=0.3,
            )

            extracted = self._parse_extraction_result(result)
            stored_count = 0

            for item in extracted:
                existing = await self._repo.find_similar(
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
        """生成 embedding 并索引到 ES"""
        if not self._search_repo or not self._embedding_factory:
            return
        try:
            embedding_client = await self._embedding_factory()
            embedding = await embedding_client.generate_embedding(entry.content)
            if not embedding:
                return
            await self._search_repo.index_memory(
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
        except Exception as e:
            logger.warning("ES 记忆索引失败", memory_id=entry.id, error=str(e))

    async def _search_es(
        self,
        agent_id: int,
        user_id: int,
        query: str,
        top_k: int,
        categories: Optional[List[str]],
    ) -> List[LongTermMemoryEntry]:
        """ES hybrid 搜索 → 回填 MySQL 完整数据"""
        try:
            embedding_client = await self._embedding_factory()
            query_vector = await embedding_client.generate_embedding(query)
            if not query_vector:
                return []

            results = await self._search_repo.search(
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
            entries: List[LongTermMemoryEntry] = []
            for r in results:
                memory = await self._repo.get_by_id(r["memory_id"])
                if memory:
                    await self._repo.increment_access_count(memory.id)
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
        categories: Optional[List[str]],
    ) -> List[LongTermMemoryEntry]:
        """MySQL LIKE fallback"""
        memories = await self._repo.search_by_keywords(
            agent_id=agent_id,
            user_id=user_id,
            query=query,
            top_k=top_k,
            categories=categories,
        )
        entries = []
        for m in memories:
            await self._repo.increment_access_count(m.id)
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
        messages: List[MemoryMessage],
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

        return PromptManager.format_prompt(
            PromptTemplate.AGENT_LONG_TERM_MEMORY.value,
            conversation_text=conversation_text,
        )

    def _parse_extraction_result(self, result: str) -> List[dict]:
        """解析 LLM 提取结果，兼容多种 JSON 格式"""
        import json
        import re

        valid_categories = {"preference", "fact", "procedure", "insight"}

        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", result)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_str = result.strip()

        array_match = re.search(r"\[[\s\S]*\]", json_str)
        if array_match:
            json_str = array_match.group(0)

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
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
