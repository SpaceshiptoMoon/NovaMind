"""
长期记忆管理器

对话结束时从消息中提取关键信息（偏好/事实/过程/洞察），
去重后持久化到 agent_memories 表。
对话开始时搜索相关记忆注入上下文。
"""
from typing import Any, Callable, List, Optional

from src.features.agent.core.memory.interfaces import (
    ILongTermMemory,
    LongTermMemoryEntry,
    MemoryMessage,
)
from src.features.agent.repository.memory_repository import MemoryRepository
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class LongTermMemory(ILongTermMemory):
    """
    长期记忆管理器

    记忆提取流程（consolidate）：
    1. 筛选包含有价值信息的对话段
    2. 使用 LLM 提取结构化记忆
    3. 与已有记忆去重比对
    4. 存入 agent_memories 表

    记忆检索流程（search）：
    1. 根据 query 关键词搜索
    2. 返回最相关的 top_k 条记忆
    3. 可按 category 过滤
    """

    def __init__(
        self,
        memory_repository: MemoryRepository,
        llm_client_factory: Callable,
    ):
        self._repo = memory_repository
        self._llm_factory = llm_client_factory

    async def store(
        self,
        agent_id: int,
        user_id: int,
        category: str,
        content: str,
        source_conversation_id: Optional[int] = None,
    ) -> LongTermMemoryEntry:
        """存储一条长期记忆"""
        memory = await self._repo.create(
            agent_id=agent_id,
            user_id=user_id,
            category=category,
            content=content,
            source_conversation_id=source_conversation_id,
        )
        logger.info(
            "长期记忆已存储",
            agent_id=agent_id,
            category=category,
            memory_id=memory.id,
        )
        return LongTermMemoryEntry(
            id=memory.id,
            agent_id=memory.agent_id,
            user_id=memory.user_id,
            category=memory.category,
            content=memory.content,
            relevance_score=memory.relevance_score,
            access_count=memory.access_count,
            source_conversation_id=memory.source_conversation_id,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )

    async def search(
        self,
        agent_id: int,
        user_id: int,
        query: str,
        top_k: int = 5,
        categories: Optional[List[str]] = None,
    ) -> List[LongTermMemoryEntry]:
        """根据查询搜索相关的长期记忆"""
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

    async def consolidate(
        self,
        agent_id: int,
        user_id: int,
        conversation_id: int,
        messages: List[MemoryMessage],
        min_turns: int = 5,
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
            messages, max_recent_turns=10, max_prompt_tokens=3000
        )
        try:
            llm = self._llm_factory()
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
                    await self.store(
                        agent_id=agent_id,
                        user_id=user_id,
                        category=item["category"],
                        content=item["content"],
                        source_conversation_id=conversation_id,
                    )
                    stored_count += 1

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

    def _build_extraction_prompt(
        self,
        messages: List[MemoryMessage],
        max_recent_turns: int = 10,
        max_prompt_tokens: int = 3000,
    ) -> str:
        """
        构建记忆提取 prompt

        成本控制：
        1. 预筛选：只取最近 max_recent_turns 条非 system 消息
        2. Token 上限：拼接后超过 max_prompt_tokens 则从头部截断
        """
        # 预筛选：只保留非 system 消息，取最近 N 条
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

        # Token 上限保护：粗略按 1 token ≈ 1.5 中文字符估算
        max_chars = max_prompt_tokens * 2
        if len(conversation_text) > max_chars:
            conversation_text = "..." + conversation_text[-max_chars:]

        return (
            "你是一个信息提取专家。请从以下对话中提取值得长期记住的关键信息。\n\n"
            "提取规则：\n"
            "1. 只提取明确的、有价值的信息，忽略寒暄和无关内容\n"
            "2. 每条信息归入以下类别之一：\n"
            "   - preference: 用户明确表达的偏好（如'我喜欢简洁的回答'）\n"
            "   - fact: 事实性信息（如'我的项目使用 Python 3.12'）\n"
            "   - procedure: 操作流程或步骤（如'部署流程是...'）\n"
            "   - insight: 有价值的洞察或结论\n"
            "3. 每条信息独立、完整、自包含\n"
            "4. 如果没有值得记住的信息，返回空数组\n\n"
            f"对话内容：\n{conversation_text}\n"
            "请以 JSON 数组格式返回，每项包含 category 和 content 两个字段：\n"
            '[{"category": "fact", "content": "..."}, ...]'
        )

    def _parse_extraction_result(self, result: str) -> List[dict]:
        """解析 LLM 提取结果，兼容多种 JSON 格式"""
        import json
        import re

        valid_categories = {"preference", "fact", "procedure", "insight"}

        # 尝试提取 JSON（可能被 markdown 代码块包裹）
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", result)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_str = result.strip()

        # 尝试提取数组部分
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

        # 过滤有效条目
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
