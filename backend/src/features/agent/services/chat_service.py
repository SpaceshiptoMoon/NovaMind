"""
Agent 对话服务

编排 Agent 对话的完整流程：会话管理 → 上下文构建（三层记忆） → ReAct 循环 → SSE 流式输出 → 结果持久化。
"""
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.features.user.services.model_config_service import ModelConfigService
from src.features.agent.services.agent_service import AgentService
from src.features.agent.core.engine import AgentEngine, AgentEvent
from src.features.agent.core.memory.short_term import ShortTermMemory
from src.features.agent.core.memory.long_term import LongTermMemory
from src.features.agent.core.memory.working import WorkingMemory
from src.features.agent.core.memory.token_budget import TokenBudget
from src.features.agent.core.memory.compress import PriorityBasedCompression
from src.features.agent.core.memory.interfaces import MemoryMessage
from src.features.agent.repository.agent_repository import MessageRepository, ToolCallRepository, SessionRepository
from src.features.agent.repository.memory_repository import MemoryRepository
from src.features.agent.models.agent import AgentDefinition
from src.features.agent.models.session import AgentSession
from src.features.agent.models.message import AgentMessage
from src.features.agent.api.exceptions import AgentError, AgentNotFoundError
from src.features.agent.tools.base import ToolContext
from src.core.middleware.structured_logging import get_logger
from src.shared.utils.time_utils import now_china
from src.features.qa.repository.chat_attachment_repository import ChatAttachmentRepository

logger = get_logger(__name__)


class AgentChatService:
    """Agent 对话服务"""

    def __init__(
        self,
        db: AsyncSession,
        agent_service: AgentService,
        model_config_service: ModelConfigService,
        agent_engine: AgentEngine,
        working_memory: WorkingMemory,
    ):
        self.db = db
        self.agent_service = agent_service
        self.model_config_service = model_config_service
        self.agent_engine = agent_engine
        self.working_memory = working_memory
        self.msg_repo = MessageRepository(db)
        self.tc_repo = ToolCallRepository(db)
        self.session_repo = SessionRepository(db)
        self.attachment_repo = ChatAttachmentRepository(db)

    async def chat_stream(
        self,
        user_id: int,
        agent_id: int,
        content: str,
        session_id: Optional[str] = None,
        llm_model: Optional[str] = None,
        enable_thinking: bool = False,
        attachment_ids: Optional[List[int]] = None,
    ) -> AsyncGenerator[str, None]:
        """执行 Agent 对话，返回 SSE 格式事件流"""
        try:
            agent, conv, user_msg = await self._prepare(
                user_id, agent_id, content, session_id, llm_model, attachment_ids
            )

            yield self._format_sse("session", {
                "session_id": conv.session_id,
                "agent_id": agent_id,
            })

            llm_client, tools, messages = await self._build_context(
                agent, conv, user_id, llm_model, content
            )

            context = ToolContext(
                db_session=self.db,
                user_id=user_id,
                agent_id=agent_id,
                session_id=conv.session_id,
            ).to_dict()

            full_response = ""

            async for event in self.agent_engine.run(
                llm_client=llm_client,
                messages=messages,
                tools=tools,
                context=context,
                enable_thinking=enable_thinking,
                max_iterations=agent.max_tool_calls_per_turn,
                max_tokens=agent.max_tokens,
                temperature=agent.temperature,
                top_p=agent.top_p,
            ):
                if event.event_type == "tool_call":
                    await self._handle_tool_call(event, user_msg, conv, context)
                    yield self._format_sse("tool_call", event.data)

                elif event.event_type == "tool_result":
                    await self._handle_tool_result(event, conv, context)
                    yield self._format_sse("tool_result", event.data)

                elif event.event_type == "reasoning":
                    yield self._format_sse("reasoning", event.data)

                elif event.event_type == "content":
                    full_response += event.data.get("content", "")
                    yield self._format_sse("content", event.data)

                elif event.event_type == "done":
                    if event.data.get("truncated", False):
                        full_response += "\n\n[Agent 已达到最大迭代次数，对话被截断]"
                    # 先 commit 再 yield done，确保数据持久化后再通知客户端
                    done_data = await self._handle_done(event, conv, content, full_response)
                    yield self._format_sse("done", done_data)
                    # 巩固长期记忆（done 事件已发送，不阻塞客户端）
                    await self._consolidate_memory(agent, conv, user_id)

                elif event.event_type == "error":
                    yield self._format_sse("error", event.data)

        except AgentNotFoundError:
            yield self._format_sse("error", {"content": "Agent 不存在"})
        except Exception as e:
            logger.error("Agent 对话失败", error=str(e))
            try:
                await self.db.rollback()
            except Exception as rollback_err:
                logger.warning("事务回滚失败", error=str(rollback_err))
            yield self._format_sse("error", {"content": f"对话失败：{str(e)}"})

    # ==================== 阶段方法 ====================

    async def _prepare(
        self,
        user_id: int,
        agent_id: int,
        content: str,
        session_id: Optional[str],
        llm_model: Optional[str],
        attachment_ids: Optional[List[int]] = None,
    ) -> tuple[AgentDefinition, AgentSession, AgentMessage]:
        """准备阶段：获取 Agent、创建/恢复会话、保存用户消息（原始 content + extra）"""
        agent = await self.agent_service.get_agent_definition(user_id, agent_id)

        conv = await self.agent_service.get_or_create_session(
            user_id, agent_id, session_id
        )

        # 解析附件，构造 extra（不修改 content）
        extra = None
        if attachment_ids:
            attachments = await self.attachment_repo.get_by_ids_and_user(attachment_ids, user_id)
            if attachments:
                extra = {"attachments": [
                    {"id": a.id, "filename": a.filename, "file_type": a.file_type, "file_size": a.file_size, "storage_path": a.storage_path}
                    for a in attachments
                ]}

        user_msg = await self.agent_service.save_message(
            conversation_id=conv.id,
            role="user",
            content=content,
            extra=extra,
        )

        return agent, conv, user_msg

    async def _build_context(
        self,
        agent: AgentDefinition,
        conv: AgentSession,
        user_id: int,
        llm_model: Optional[str],
        user_content: str,
    ) -> tuple[Any, List[Dict], List[Dict]]:
        """构建阶段：获取 LLM 客户端、工具列表、上下文消息（三层记忆）"""
        # LLM 客户端
        model = llm_model or agent.llm_model
        if not model:
            model = await self.model_config_service.get_default_model_name("llm")
        if not model:
            raise AgentError("未配置可用的 LLM 模型，请在系统设置中配置默认模型")
        llm_client = await self.model_config_service.get_llm_client_by_model(user_id, model)

        # 工具列表
        tool_executor = self.agent_engine.tool_executor
        enabled_tools = agent.enabled_tools or []
        enabled_mcp_ids = agent.enabled_mcp_servers or []
        tools = tool_executor.resolve_tools(enabled_tools, enabled_mcp_ids)

        # 构建系统提示词
        system_prompt = agent.system_prompt
        if "{tools}" in system_prompt:
            tool_names = ", ".join(enabled_tools) if enabled_tools else "无"
            system_prompt = system_prompt.format(
                tools=tool_names,
                current_date=now_china().strftime("%Y-%m-%d"),
            )

        # 注入内置工具的系统提示词片段
        tool_fragments = self._collect_tool_prompt_fragments(enabled_tools)
        if tool_fragments:
            system_prompt += "\n\n---\n\n" + "\n\n".join(tool_fragments)

        # 注入技能广场的 Markdown 指令
        skill_fragments = await self._collect_skill_fragments(enabled_tools)
        if skill_fragments:
            system_prompt += "\n\n---\n\n" + "\n\n".join(skill_fragments)

        # 长期记忆：检索相关记忆注入系统提示词
        system_prompt = await self._inject_long_term_memories(
            agent, conv, user_id, system_prompt, user_content
        )

        # 短期记忆：Token 预算管理 + 自动压缩
        short_term = ShortTermMemory(
            message_repository=self.msg_repo,
            tool_call_repository=self.tc_repo,
            session_repository=self.session_repo,
            token_budget=TokenBudget(model),
            compression_strategy=PriorityBasedCompression(),
        )
        snapshot = await short_term.build_context(
            system_prompt=system_prompt,
            conversation_id=conv.id,
            max_tokens=agent.context_window or 32768,
        )

        if snapshot.compressed:
            logger.info(
                "上下文已压缩",
                conversation_id=conv.id,
                compression_ratio=snapshot.compression_ratio,
                tokens=snapshot.total_tokens,
            )

        # 动态注入附件文本到上下文
        # 用 try/except 包裹，注入失败不应阻塞对话
        try:
            await self._inject_attachments_to_snapshot(snapshot, conv.id, user_id)
        except Exception as inject_err:
            logger.warning("附件文本注入失败，跳过注入", error=str(inject_err))

        return llm_client, tools, snapshot.messages

    # ==================== 附件动态注入 ====================

    async def _inject_attachments_to_snapshot(self, snapshot, conversation_id: int, user_id: int) -> None:
        """扫描 snapshot.messages，为有附件的用户消息动态注入 XML 文档文本"""
        from sqlalchemy import select
        from src.features.agent.models.message import AgentMessage

        # 查询该会话中所有带附件的用户消息（按时间排序，用于按位置匹配）
        stmt = select(AgentMessage).where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.role == "user",
            AgentMessage.extra.isnot(None),
        ).order_by(AgentMessage.created_at.asc())
        result = await self.db.execute(stmt)
        messages_with_extra = list(result.scalars().all())

        if not messages_with_extra:
            return

        # 用消息在数据库列表中的索引作为关联键（避免重复内容导致丢失附件）
        msg_att_list = []  # [(attachment_ids, ...)]
        all_att_ids = []
        for msg in messages_with_extra:
            atts = (msg.extra or {}).get("attachments") or []
            if atts:
                ids = [a["id"] for a in atts if "id" in a]
                msg_att_list.append(ids)
                all_att_ids.extend(ids)
            else:
                msg_att_list.append([])

        if not all_att_ids:
            return

        att_records = await self.attachment_repo.get_by_ids(all_att_ids, user_id=user_id)
        att_by_id = {a.id: a for a in att_records}

        # 按 user 消息在 snapshot.messages 中的位置索引匹配
        user_msg_idx = 0  # 当前匹配到的带附件用户消息索引
        for item in snapshot.messages:
            if item.get("role") != "user":
                continue
            if user_msg_idx >= len(msg_att_list):
                break
            att_ids = msg_att_list[user_msg_idx]
            if not att_ids:
                user_msg_idx += 1
                continue
            user_msg_idx += 1
            records = [att_by_id[aid] for aid in att_ids if aid in att_by_id]
            if records:
                xml = self._format_attachments_prompt(records)
                content = item.get("content", "")
                item["content"] = f"{xml}\n\n用户问题：{content}"

    # ==================== 内置工具提示词注入 ====================

    def _format_attachments_prompt(self, attachments: list) -> str:
        """将附件文本格式化为 XML 结构的 LLM 提示"""
        docs = []
        for att in attachments:
            text = att.extracted_text or "(无法提取文档文本)"
            docs.append(f'  <document filename="{att.filename}">\n{text}\n  </document>')
        return "<documents>\n" + "\n".join(docs) + "\n</documents>"

    def _collect_tool_prompt_fragments(self, enabled_tools: list) -> list:
        """收集已启用的内置工具的 system_prompt_fragment"""
        fragments = []
        registry = self.agent_engine.tool_executor.tool_registry
        for tool_name in enabled_tools:
            if tool_name.startswith("skill__"):
                continue
            tool = registry.get_tool(tool_name)
            if tool:
                fragment = tool.get_system_prompt_fragment()
                if fragment:
                    fragments.append(fragment)
        return fragments

    # ==================== 技能指令注入 ====================

    async def _collect_skill_fragments(self, enabled_tools: list) -> list:
        """收集技能广场中已安装技能的 Markdown 指令片段"""
        from src.features.skill.models.skill import SkillStatus, ReviewStatus

        fragments = []
        for skill_ref in enabled_tools:
            if not skill_ref.startswith("skill__"):
                continue
            try:
                # 格式: skill__{id}_{name}
                parts = skill_ref.split("_", 2)
                if len(parts) < 3:
                    continue
                skill_id = int(parts[1])
                from src.features.skill.repository.skill_repository import SkillRepository
                repo = SkillRepository(self.db)
                skill_def = await repo.get_by_id(skill_id)
                if (
                    skill_def
                    and skill_def.body_markdown
                    and skill_def.status == SkillStatus.PUBLISHED
                    and skill_def.review_status == ReviewStatus.APPROVED
                ):
                    fragments.append(
                        f"## 技能: {skill_def.display_name}\n\n{skill_def.body_markdown}"
                    )
            except (ValueError, IndexError, Exception) as e:
                logger.warning("技能指令注入失败", skill_ref=skill_ref, error=str(e))
        return fragments

    # ==================== 长期记忆注入 ====================

    async def _inject_long_term_memories(
        self,
        agent: AgentDefinition,
        conv: AgentSession,
        user_id: int,
        system_prompt: str,
        user_content: str,
    ) -> str:
        """检索长期记忆并注入系统提示词"""
        try:
            memory_repo = MemoryRepository(self.db)
            # search 只用关键词匹配，不需要 LLM 客户端
            long_term = LongTermMemory(memory_repo, llm_client_factory=lambda: None)

            relevant = await long_term.search(
                agent_id=agent.id,
                user_id=user_id,
                query=user_content,
                top_k=3,
            )

            if relevant:
                memory_lines = [
                    f"- [{m.category}] {m.content}"
                    for m in relevant
                ]
                memory_text = "\n".join(memory_lines)
                system_prompt += f"\n\n## 关于该用户的长期记忆\n{memory_text}"
                logger.debug(
                    "长期记忆已注入",
                    agent_id=agent.id,
                    memories_count=len(relevant),
                )

        except Exception as e:
            logger.warning("长期记忆检索失败，跳过注入", error=str(e))

        return system_prompt

    # ==================== 事件处理 ====================

    async def _handle_tool_call(
        self,
        event: AgentEvent,
        user_msg: AgentMessage,
        conv: AgentSession,
        context: Dict[str, Any],
    ) -> None:
        """处理 tool_call 事件：保存工具调用记录"""
        call_id = event.data.get("call_id", "")
        tc = await self.tc_repo.create(
            message_id=user_msg.id,
            conversation_id=conv.id,
            tool_name=event.data["tool_name"],
            tool_source="mcp" if event.data["tool_name"].startswith("mcp__") else "skill" if event.data["tool_name"].startswith("skill__") else "builtin",
            arguments=event.data.get("arguments", {}),
            status="running",
        )
        context[f"tc_{call_id}"] = tc.id

    async def _handle_tool_result(
        self,
        event: AgentEvent,
        conv: AgentSession,
        context: Dict[str, Any],
    ) -> None:
        """处理 tool_result 事件：更新调用记录、保存工具结果消息"""
        call_id = event.data.get("call_id", "")
        tc_id = context.get(f"tc_{call_id}")
        if tc_id:
            await self.tc_repo.update(
                tc_id,
                result=event.data.get("result", ""),
                status=event.data.get("status", "completed"),
                duration_ms=event.data.get("duration_ms"),
            )

        await self.agent_service.save_message(
            conversation_id=conv.id,
            role="tool",
            content=event.data.get("result", ""),
            tool_call_id=call_id,
            tool_name=event.data.get("tool_name"),
        )

    async def _handle_done(
        self,
        event: AgentEvent,
        conv: AgentSession,
        user_content: str,
        full_response: str,
    ) -> Dict[str, Any]:
        """处理 done 事件：保存 assistant 消息、更新统计、设置标题"""
        total_tokens = event.data.get("total_tokens", 0)

        assistant_msg = await self.agent_service.save_message(
            conversation_id=conv.id,
            role="assistant",
            content=full_response,
            token_count=total_tokens,
        )

        await self.agent_service.update_session_stats(conv.id, total_tokens)

        # 更新会话标题
        await self.db.refresh(conv)
        if conv.message_count <= 1 and not conv.title:
            title = user_content[:50] + ("..." if len(user_content) > 50 else "")
            await self.session_repo.update(conv.id, title=title)

        await self.db.commit()

        event.data["message_id"] = assistant_msg.id
        return event.data

    # ==================== 工具方法 ====================

    def _format_sse(self, event_type: str, data: dict) -> str:
        """格式化 SSE 事件"""
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    # ==================== 长期记忆巩固 ====================

    async def _consolidate_memory(
        self,
        agent: AgentDefinition,
        conv: AgentSession,
        user_id: int,
    ) -> None:
        """巩固长期记忆：从对话中提取有价值的信息存入 agent_memories 表"""
        try:
            # 获取 LLM 客户端（同步工厂，避免改 LongTermMemory 接口）
            model = agent.llm_model
            if not model:
                model = await self.model_config_service.get_default_model_name("llm")
            if not model:
                return
            llm_client = await self.model_config_service.get_llm_client_by_model(user_id, model)

            memory_repo = MemoryRepository(self.db)
            long_term_memory = LongTermMemory(memory_repo, lambda: llm_client)

            # 加载对话消息并转换为 MemoryMessage
            db_messages, _ = await self.msg_repo.list_by_conversation(conv.id, limit=50)
            memory_messages = [
                MemoryMessage(
                    role=m.role,
                    content=m.content or "",
                    tool_name=m.tool_name,
                    tool_call_id=m.tool_call_id,
                )
                for m in db_messages
            ]

            stored = await long_term_memory.consolidate(
                agent_id=agent.id,
                user_id=user_id,
                conversation_id=conv.id,
                messages=memory_messages,
                min_turns=5,
            )

            if stored > 0:
                logger.info("长期记忆巩固完成", agent_id=agent.id, stored=stored)
                await self.db.commit()

        except Exception as e:
            logger.warning("长期记忆巩固失败", error=str(e))
