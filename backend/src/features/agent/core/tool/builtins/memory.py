"""
内置工具：记忆管理

允许 Agent 主动添加、替换、移除长期记忆。
所有写入操作经过安全扫描。
"""
import json
from typing import Any, Dict, List

from src.features.agent.core.tool.base import BaseTool
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

_MEMORY_LIMIT_PER_USER_AGENT = 50


class MemoryTool(BaseTool):
    """记忆管理工具"""

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return "长期记忆管理工具"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "memory",
                    "description": (
                        "Save durable information to persistent memory that survives across sessions. "
                        "Memory is injected into future turns, so keep it compact and focused on facts "
                        "that will still matter later.\n\n"
                        "WHEN TO SAVE (do this proactively, don't wait to be asked):\n"
                        "- User corrects you or says 'remember this' / 'don't do that again'\n"
                        "- User shares a preference, habit, or personal detail (name, role, timezone, coding style)\n"
                        "- You discover something about the environment (project structure, tool behavior, API quirks)\n"
                        "- You learn a convention or workflow specific to this user's setup\n"
                        "- You identify a stable fact that will be useful again in future sessions\n\n"
                        "PRIORITY: User preferences and corrections > environment facts > procedural knowledge. "
                        "The most valuable memory prevents the user from having to repeat themselves.\n\n"
                        "Do NOT save task progress, session outcomes, completed-work logs, or temporary TODO state. "
                        "Do NOT save trivial/obvious info, things easily re-discovered, or raw data dumps.\n\n"
                        "CATEGORIES:\n"
                        "- preference: User's personal preferences (response style, language, tools)\n"
                        "- fact: Stable facts about the user, project, or environment\n"
                        "- procedure: Workflows or processes the user follows\n"
                        "- insight: Lessons learned, key decisions, or important observations\n\n"
                        "ACTIONS: add (new entry), replace (update existing -- old_content identifies it), "
                        "remove (delete -- old_content identifies it)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["add", "replace", "remove"],
                                "description": "The action to perform.",
                            },
                            "category": {
                                "type": "string",
                                "enum": ["preference", "fact", "procedure", "insight"],
                                "description": "Memory category.",
                            },
                            "content": {
                                "type": "string",
                                "description": "The memory content. Required for 'add' and 'replace'. Keep it 1-2 sentences.",
                            },
                            "old_content": {
                                "type": "string",
                                "description": "Short unique substring identifying the entry to replace or remove.",
                            },
                        },
                        "required": ["action", "category"],
                    },
                },
            },
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        if tool_name != "memory":
            return json.dumps({"error": f"未知工具：{tool_name}"}, ensure_ascii=False)

        action = arguments.get("action", "")
        dispatch = {
            "add": lambda: self._add(arguments, context),
            "replace": lambda: self._replace(arguments, context),
            "remove": lambda: self._remove(arguments, context),
        }
        handler = dispatch.get(action)
        if handler:
            return await handler()
        return json.dumps({"error": f"未知操作：{action}"}, ensure_ascii=False)

    async def _add(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        """添加记忆"""
        try:
            from src.features.agent.core.memory.security import scan_memory_content
            from src.features.agent.repository.memory_repository import MemoryRepository

            category = args["category"]
            content = args.get("content", "")
            if not content:
                return json.dumps({"error": "add 操作必须提供 content"}, ensure_ascii=False)

            db = context["db_session"]
            user_id = context["user_id"]
            agent_id = context["agent_id"]

            scan = scan_memory_content(content)
            if not scan:
                logger.warning("记忆写入被安全扫描拦截", threats=scan.threats)
                return json.dumps(
                    {"error": "记忆内容未通过安全检查", "threats": scan.threats},
                    ensure_ascii=False,
                )

            repo = MemoryRepository(db)

            # 记忆数量上限检查
            existing, total = await repo.list_by_agent(agent_id, user_id, limit=1)
            if total >= _MEMORY_LIMIT_PER_USER_AGENT:
                return json.dumps(
                    {"error": f"记忆数量已达上限 ({_MEMORY_LIMIT_PER_USER_AGENT} 条)，请先移除旧记忆"},
                    ensure_ascii=False,
                )

            existing = await repo.find_similar(agent_id, user_id, category, content)
            if existing:
                return json.dumps(
                    {"message": "相同记忆已存在，未重复添加", "id": existing.id},
                    ensure_ascii=False,
                )

            memory = await repo.create(
                agent_id=agent_id,
                user_id=user_id,
                category=category,
                content=content,
            )
            await db.flush()

            try:
                await self._index_to_es(memory, db, user_id)
            except Exception as e:
                logger.warning("记忆 ES 索引失败，仅 MySQL 写入", error=str(e))

            return json.dumps(
                {"message": "记忆已添加", "id": memory.id, "category": category},
                ensure_ascii=False,
            )
        except Exception as e:
            logger.error("添加记忆失败", error=str(e))
            return json.dumps({"error": f"添加记忆失败：{str(e)}"}, ensure_ascii=False)

    async def _replace(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        """替换记忆"""
        try:
            from src.features.agent.core.memory.security import scan_memory_content
            from src.features.agent.repository.memory_repository import MemoryRepository

            old_content = args.get("old_content", "")
            new_content = args.get("content", "")
            if not old_content or not new_content:
                return json.dumps({"error": "replace 操作必须提供 old_content 和 content"}, ensure_ascii=False)

            db = context["db_session"]
            user_id = context["user_id"]
            agent_id = context["agent_id"]

            scan = scan_memory_content(new_content)
            if not scan:
                return json.dumps(
                    {"error": "新内容未通过安全检查", "threats": scan.threats},
                    ensure_ascii=False,
                )

            repo = MemoryRepository(db)
            from src.features.agent.models.memory import AgentMemory
            from sqlalchemy import select

            stmt = select(AgentMemory).where(
                AgentMemory.agent_id == agent_id,
                AgentMemory.user_id == user_id,
                AgentMemory.content.contains(old_content),
            )
            result = await db.execute(stmt)
            memory = result.scalar_one_or_none()

            if not memory:
                return json.dumps(
                    {"error": "未找到匹配的记忆，请确保 old_content 包含正确的内容片段"},
                    ensure_ascii=False,
                )

            await repo.update(memory.id, content=new_content)
            await db.flush()

            return json.dumps(
                {"message": "记忆已更新", "id": memory.id},
                ensure_ascii=False,
            )
        except Exception as e:
            logger.error("替换记忆失败", error=str(e))
            return json.dumps({"error": f"替换记忆失败：{str(e)}"}, ensure_ascii=False)

    async def _remove(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        """移除记忆"""
        try:
            from src.features.agent.repository.memory_repository import MemoryRepository
            from src.features.agent.models.memory import AgentMemory
            from sqlalchemy import select

            old_content = args.get("old_content", "")
            if not old_content:
                return json.dumps({"error": "remove 操作必须提供 old_content"}, ensure_ascii=False)

            db = context["db_session"]
            user_id = context["user_id"]
            agent_id = context["agent_id"]

            stmt = select(AgentMemory).where(
                AgentMemory.agent_id == agent_id,
                AgentMemory.user_id == user_id,
                AgentMemory.content.contains(old_content),
            )
            result = await db.execute(stmt)
            memory = result.scalar_one_or_none()

            if not memory:
                return json.dumps(
                    {"error": "未找到匹配的记忆"},
                    ensure_ascii=False,
                )

            repo = MemoryRepository(db)
            await repo.delete(memory.id)
            await db.flush()

            try:
                from src.features.agent.repository.memory_search_repository import MemorySearchRepository
                from src.shared.clients import ClientFactory
                es_wrapper = await ClientFactory.get_elasticsearch_client()
                search_repo = MemorySearchRepository(es_client=es_wrapper.es_client)
                await search_repo.delete_memory(agent_id, memory.id)
            except Exception as e:
                logger.warning("ES 记忆删除失败", error=str(e))

            return json.dumps(
                {"message": "记忆已移除", "id": memory.id},
                ensure_ascii=False,
            )
        except Exception as e:
            logger.error("移除记忆失败", error=str(e))
            return json.dumps({"error": f"移除记忆失败：{str(e)}"}, ensure_ascii=False)

    async def _index_to_es(self, memory, db, user_id: int) -> None:
        """将记忆索引到 ES"""
        from src.features.agent.repository.memory_search_repository import MemorySearchRepository
        from src.shared.clients import ClientFactory

        es_wrapper = await ClientFactory.get_elasticsearch_client()
        search_repo = MemorySearchRepository(es_client=es_wrapper.es_client)

        from src.features.user.services.model_config_service import ModelConfigService
        model_config_service = ModelConfigService(db)
        embedding_model = await model_config_service.get_default_model_name("embedding")
        if not embedding_model:
            return

        embedding_client = await model_config_service.get_embedding_client_by_model(
            user_id, embedding_model
        )
        vector = await embedding_client.generate_embedding(memory.content)
        await search_repo.ensure_index(memory.agent_id)
        await search_repo.index_memory(
            agent_id=memory.agent_id,
            memory_id=memory.id,
            user_id=memory.user_id,
            category=memory.category,
            content=memory.content,
            embedding=vector,
            source_type="manual",
            created_at=memory.created_at,
        )

    def get_system_prompt_fragment(self) -> str:
        return (
            "You have persistent memory across sessions. Save durable facts using the memory "
            "tool: user preferences, environment details, tool quirks, and stable conventions. "
            "Memory is injected into every turn, so keep it compact and focused on facts that "
            "will still matter later.\n"
            "Prioritize what reduces future user steering — the most valuable memory is one "
            "that prevents the user from having to correct or remind you again. "
            "User preferences and recurring corrections matter more than procedural task details.\n"
            "Do NOT save task progress, session outcomes, completed-work logs, or temporary TODO "
            "state to memory.\n"
            "Write memories as declarative facts, not instructions to yourself. "
            "'User prefers concise responses' ✓ — 'Always respond concisely' ✗. "
            "'Project uses pytest with xdist' ✓ — 'Run tests with pytest -n 4' ✗. "
            "Imperative phrasing gets re-read as a directive in later sessions and can "
            "cause repeated work or override the user's current request."
        )
