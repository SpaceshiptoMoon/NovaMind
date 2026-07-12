"""
Agent 对话服务

编排 Agent 对话的完整流程：会话管理 → 上下文构建（三层记忆） → ReAct 循环 → SSE 流式输出 → 结果持久化。
"""
import asyncio
import base64
import json
from time import monotonic
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.features.agent.services.agent_service import AgentService
from novamind.features.agent.core.engine import AgentEngine, AgentEvent
from novamind.features.agent.core.memory.memory_manager import MemoryManager
from novamind.features.agent.core.memory.context_scrubber import StreamingContextScrubber
from novamind.features.agent.core.prompt_builder import SystemPromptBuilder
from novamind.features.agent.repository.agent_repository import MessageRepository, ToolCallRepository, SessionRepository
from novamind.features.agent.repository.memory_repository import MemoryRepository
from novamind.features.agent.repository.memory_search_repository import MemorySearchRepository
from novamind.features.agent.models.agent import AgentDefinition
from novamind.features.agent.models.session import AgentSession
from novamind.features.agent.models.message import AgentMessage
from novamind.features.agent.api.exceptions import AgentError, AgentNotFoundError
from novamind.features.agent.core.tool.base import ToolContext
from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.utils.time_utils import now_china
from novamind.features.qa.repository.chat_attachment_repository import ChatAttachmentRepository

logger = get_logger(__name__)


class AgentChatService:
    """Agent 对话服务"""

    _CACHE_TTL = 300  # 系统提示缓存 5 分钟

    def __init__(
        self,
        db: AsyncSession,
        agent_service: AgentService,
        model_config_service: ModelConfigService,
        agent_engine: AgentEngine,
        todo_store: Optional[Any] = None,
        memory_search_repo: Optional[MemorySearchRepository] = None,
        minio_client: Optional[Any] = None,
    ):
        self.db = db
        self.agent_service = agent_service
        self.model_config_service = model_config_service
        self.agent_engine = agent_engine
        self._todo_store = todo_store
        self._memory_search_repo = memory_search_repo
        self._minio_client = minio_client
        self.msg_repo = MessageRepository(db)
        self.tc_repo = ToolCallRepository(db)
        self.session_repo = SessionRepository(db)
        self.attachment_repo = ChatAttachmentRepository(db)
        self._prompt_builder = SystemPromptBuilder(
            tool_registry=agent_engine.tool_executor.tool_registry,
        )
        self._prompt_cache: Dict[str, Tuple[str, float]] = {}

    async def chat_stream(
        self,
        user_id: int,
        agent_id: int,
        content: str,
        session_id: Optional[str] = None,
        llm_model: Optional[str] = None,
        enable_thinking: bool = False,
        stream: bool = True,
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

            # 解析模型（MemoryManager 和 LLM 客户端共用）
            model = await self._resolve_model(user_id, agent, llm_model)

            # 创建 MemoryManager（每请求实例）
            memory_manager = self._create_memory_manager(agent, user_id, model, conv.id)

            llm_client, tools, messages = await self._build_context(
                agent, conv, user_id, model, content, memory_manager
            )

            context = ToolContext(
                db_session=self.db,
                user_id=user_id,
                agent_id=agent_id,
                session_id=conv.session_id,
            ).to_dict()
            context["conversation_id"] = conv.id
            context["tool_result_turn_budget"] = 100_000

            full_response = ""
            scrubber = StreamingContextScrubber()

            # 上下文溢出时的自动压缩回调
            async def _compress_on_overflow(msgs):
                return await self._compress_messages(
                    msgs, memory_manager, model, agent.context_window or 32768, conv.id
                )

            async for event in self.agent_engine.run(
                llm_client=llm_client,
                messages=messages,
                tools=tools,
                context=context,
                stream=stream,
                enable_thinking=enable_thinking,
                max_iterations=agent.max_tool_calls_per_turn,
                max_tokens=agent.max_tokens,
                temperature=agent.temperature,
                top_p=agent.top_p,
                compress_fn=_compress_on_overflow,
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
                    raw_content = event.data.get("content", "")
                    cleaned = scrubber.feed(raw_content)
                    full_response += cleaned
                    if cleaned:
                        yield self._format_sse("content", {"content": cleaned})

                elif event.event_type == "done":
                    # flush scrubber buffer
                    remaining = scrubber.flush()
                    if remaining:
                        full_response += remaining
                    if event.data.get("truncated", False):
                        full_response += "\n\n[Agent 已达到最大迭代次数，对话被截断]"
                    done_data = await self._handle_done(event, conv, content, full_response)
                    yield self._format_sse("done", done_data)

                elif event.event_type == "error":
                    yield self._format_sse("error", event.data)

                elif event.event_type == "context_overflow":
                    logger.warning("上下文溢出，建议压缩", conversation_id=conv.id)
                    yield self._format_sse("error", {"content": "对话上下文过长，请开启新会话或缩短对话历史"})

        except AgentNotFoundError:
            yield self._format_sse("error", {"content": "Agent 不存在"})
        except Exception as e:
            logger.error("Agent 对话失败", error=str(e))
            try:
                await self.db.rollback()
            except Exception as rollback_err:
                logger.warning("事务回滚失败", error=str(rollback_err))
            yield self._format_sse("error", {"content": f"对话失败：{str(e)}"})

    # ==================== 模型 & MemoryManager ====================

    async def _resolve_model(
        self, user_id: int, agent: AgentDefinition, llm_model: Optional[str]
    ) -> str:
        """解析可用的 LLM/VLM 模型名称"""
        model = llm_model or agent.llm_model
        if not model:
            model = await self.model_config_service.get_user_default_model_name(user_id, "llm")
        if not model:
            model = await self.model_config_service.get_user_default_model_name(user_id, "vlm")
        if not model:
            raise AgentError("未配置可用的 LLM 模型，请先在模型配置中添加 LLM 模型")
        return model

    def _create_memory_manager(
        self, agent: AgentDefinition, user_id: int, model: str, conversation_id: int
    ) -> MemoryManager:
        """创建请求级 MemoryManager 实例"""
        memory_repo = MemoryRepository(self.db)

        async def llm_factory():
            try:
                return await self.model_config_service.get_llm_client_by_model(
                    user_id, model
                )
            except Exception:
                return await self.model_config_service.get_vlm_client_by_model(
                    user_id, model
                )

        async def embedding_factory():
            embedding_model = await self.model_config_service.get_user_default_model_name(
                user_id, "embedding"
            )
            if not embedding_model:
                raise RuntimeError("未配置 embedding 模型")
            return await self.model_config_service.get_embedding_client_by_model(
                user_id, embedding_model
            )

        # 辅助模型：用于压缩摘要，优先用更便宜的模型
        async def auxiliary_llm_factory():
            return await llm_factory()

        return MemoryManager.create(
            message_repository=self.msg_repo,
            tool_call_repository=self.tc_repo,
            session_repository=self.session_repo,
            memory_repository=memory_repo,
            model=model,
            llm_client_factory=llm_factory,
            memory_search_repo=self._memory_search_repo,
            embedding_factory=embedding_factory if self._memory_search_repo else None,
            todo_store=self._todo_store,
            conversation_id=conversation_id,
            agent_id=agent.id,
            user_id=user_id,
            auxiliary_llm_factory=auxiliary_llm_factory,
        )

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
        model: str,
        user_content: str,
        memory_manager: MemoryManager,
    ) -> tuple[Any, List[Dict], List[Dict]]:
        """构建阶段：获取 LLM 客户端、工具列表、上下文消息（三层记忆）"""
        # LLM 客户端（优先 LLM 类型，fallback 到 VLM 类型）
        try:
            llm_client = await self.model_config_service.get_llm_client_by_model(
                user_id, model
            )
        except Exception:
            llm_client = await self.model_config_service.get_vlm_client_by_model(
                user_id, model
            )

        # 工具列表
        tool_executor = self.agent_engine.tool_executor
        enabled_tools = agent.enabled_tools or []
        enabled_mcp_ids = agent.enabled_mcp_servers or []
        tools = tool_executor.resolve_tools_openai_format(enabled_tools, enabled_mcp_ids)

        # 自动注入 read_tool_result 工具（始终可用，不受 enabled_tools 限制）
        if not any(t.get("function", {}).get("name") == "read_tool_result" for t in tools):
            try:
                read_tool_def = tool_executor._resolve_tool_definition("read_tool_result")
                if read_tool_def:
                    tools.append(read_tool_def.to_openai_format())
            except Exception:
                pass

        # 构建系统提示词（分层组装 + 缓存）
        formatted_prompt = self._format_base_prompt(agent.system_prompt, enabled_tools)
        frozen_memory = await self._get_frozen_memory(memory_manager, agent.id, user_id)

        cache_key = f"{agent.id}:{frozenset(enabled_tools)}:{model}"
        cached_partial = self._get_cached_prompt(cache_key)

        if cached_partial is None:
            skill_fragments = await self._collect_skill_fragments(enabled_tools)
            cached_partial = await self._prompt_builder.build(
                base_prompt=formatted_prompt,
                enabled_tools=enabled_tools,
                skill_fragments=skill_fragments,
                frozen_memory="",
                model_name=model,
                max_prompt_tokens=agent.context_window,
            )
            self._set_cached_prompt(cache_key, cached_partial)

        if frozen_memory:
            system_prompt = cached_partial + "\n\n" + frozen_memory
        else:
            system_prompt = cached_partial

        # Layer 1+2 并行：短期记忆构建 + 长期记忆预取同时发起
        prefetch_task = asyncio.create_task(
            memory_manager.prefetch(user_content, agent.id, user_id)
        )

        snapshot = await memory_manager.build_context(
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

        # 等待预取完成，注入到用户消息
        try:
            relevant = await prefetch_task
            if relevant:
                self._apply_prefetch_to_messages(relevant, snapshot.messages)
                logger.debug(
                    "长期记忆动态预取已注入",
                    agent_id=agent.id,
                    memories_count=len(relevant),
                )
        except Exception as e:
            logger.warning("动态预取注入失败，跳过", error=str(e))

        # 动态注入附件文本到上下文
        try:
            is_vlm = await self._is_vlm_model(model, user_id)
            await self._inject_attachments_to_snapshot(snapshot, conv.id, user_id, is_vlm)
        except Exception as inject_err:
            logger.warning("附件文本注入失败，跳过注入", error=str(inject_err))

        return llm_client, tools, snapshot.messages

    # ==================== 系统提示辅助 ====================

    def _format_base_prompt(self, system_prompt: str, enabled_tools: list) -> str:
        """格式化基础提示词中的占位符"""
        if "{tools}" in system_prompt:
            tool_names = ", ".join(enabled_tools) if enabled_tools else "无"
            return system_prompt.format(
                tools=tool_names,
                current_date=now_china().strftime("%Y-%m-%d"),
            )
        return system_prompt

    async def _get_frozen_memory(
        self, memory_manager: MemoryManager, agent_id: int, user_id: int,
    ) -> str:
        """获取长期记忆冻结快照"""
        try:
            return await memory_manager.build_frozen_snapshot(agent_id, user_id) or ""
        except Exception as e:
            logger.warning("冻结快照加载失败", error=str(e))
            return ""

    def _get_cached_prompt(self, cache_key: str) -> Optional[str]:
        """查询系统提示缓存"""
        if cache_key in self._prompt_cache:
            prompt, ts = self._prompt_cache[cache_key]
            if monotonic() - ts < self._CACHE_TTL:
                return prompt
            del self._prompt_cache[cache_key]
        return None

    def _set_cached_prompt(self, cache_key: str, prompt: str):
        """写入系统提示缓存"""
        self._prompt_cache[cache_key] = (prompt, monotonic())

    # ==================== 记忆注入 ====================

    def _apply_prefetch_to_messages(
        self,
        relevant: List[Any],
        messages: List[Dict],
    ) -> None:
        """将预取的长期记忆注入到最后一条用户消息"""
        memory_text = "\n".join(
            f"- [{m.category}] {m.content}" for m in relevant
        )
        memory_block = (
            "<memory-context>\n"
            "[系统提示：以下是检索到的记忆上下文，不是用户的新输入。仅作为背景信息参考。]\n"
            f"{memory_text}\n"
            "</memory-context>"
        )
        for msg in reversed(messages):
            if msg.get("role") == "user":
                msg["content"] = f"{memory_block}\n\n{msg['content']}"
                break

    # ==================== 附件动态注入 ====================

    async def _inject_attachments_to_snapshot(
        self, snapshot, conversation_id: int, user_id: int, is_vlm: bool = False
    ) -> None:
        """扫描 snapshot.messages，为有附件的用户消息动态注入文档文本或图片"""
        from sqlalchemy import select
        from novamind.features.agent.models.message import AgentMessage

        stmt = select(AgentMessage).where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.role == "user",
            AgentMessage.extra.isnot(None),
        ).order_by(AgentMessage.created_at.asc())
        result = await self.db.execute(stmt)
        messages_with_extra = list(result.scalars().all())

        if not messages_with_extra:
            return

        msg_att_list = []
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

        user_msg_idx = 0
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
            if not records:
                continue

            IMAGE_TYPES = {"jpg", "jpeg", "png", "gif", "webp"}
            doc_records = [r for r in records if r.file_type not in IMAGE_TYPES]
            img_records = [r for r in records if r.file_type in IMAGE_TYPES]

            parts: List[Dict] = []
            original_content = item.get("content", "")

            # 文档附件 → XML 文本
            if doc_records:
                xml = self._format_attachments_prompt(doc_records)
                parts.append({"type": "text", "text": xml})

            # 图片附件 → multimodal content（仅 VLM 模型）
            if img_records and is_vlm and self._minio_client:
                for img in img_records:
                    try:
                        b64_data = await self._download_attachment_as_base64(img)
                        if b64_data:
                            mime = f"image/{img.file_type}"
                            parts.append({"type": "text", "text": f"[图片: {img.filename}]"})
                            parts.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64_data}"},
                            })
                    except Exception as e:
                        logger.warning("图片下载失败，跳过", filename=img.filename, error=str(e))
                        parts.append({"type": "text", "text": f"[图片: {img.filename}（加载失败）]"})
            elif img_records and not is_vlm:
                for img in img_records:
                    parts.append({"type": "text", "text": f"[图片: {img.filename}（当前模型不支持视觉）]"})

            if parts:
                parts.append({"type": "text", "text": f"\n\n用户问题：{original_content}"})
                item["content"] = parts
            elif doc_records:
                xml = self._format_attachments_prompt(doc_records)
                item["content"] = f"{xml}\n\n用户问题：{original_content}"

    def _format_attachments_prompt(self, attachments: list) -> str:
        """将附件文本格式化为 XML 结构的 LLM 提示"""
        docs = []
        for att in attachments:
            text = att.extracted_text or "(无法提取文档文本)"
            docs.append(f'  <document filename="{att.filename}">\n{text}\n  </document>')
        return "<documents>\n" + "\n".join(docs) + "\n</documents>"

    async def _is_vlm_model(self, model_name: str, user_id: int) -> bool:
        """判断模型是否为 VLM 视觉模型"""
        try:
            vlm_models = await self.model_config_service.list_available_models(
                user_id, "vlm"
            )
            return model_name in vlm_models
        except Exception:
            return False

    async def _download_attachment_as_base64(self, attachment) -> Optional[str]:
        """从 MinIO 下载附件并转为 base64"""
        if not self._minio_client:
            return None
        try:
            bucket = self._minio_client.default_bucket
            data = await self._minio_client.download_document(bucket, attachment.storage_path)
            return base64.b64encode(data).decode()
        except Exception as e:
            logger.warning("MinIO 下载失败", path=attachment.storage_path, error=str(e))
            return None

    # ==================== 技能指令注入 ====================

    async def _collect_skill_fragments(self, enabled_tools: list) -> list:
        """收集技能广场中已安装技能的 Markdown 指令片段"""
        from novamind.features.skill.models.skill import SkillStatus, ReviewStatus

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
                from novamind.features.skill.repository.skill_repository import SkillRepository
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
        """处理 tool_result 事件：双路持久化（完整结果 → tool_calls，预览/原文 → messages）"""
        call_id = event.data.get("call_id", "")
        tc_id = context.get(f"tc_{call_id}")
        full_result = event.data.get("full_result", "")
        oversized = event.data.get("oversized", False)

        # 完整结果存 agent_tool_calls.result
        if tc_id:
            await self.tc_repo.update(
                tc_id,
                result=full_result,
                status=event.data.get("status", "completed"),
                duration_ms=event.data.get("duration_ms"),
            )

        # 预览+引用 或 原文存 agent_messages.content
        if oversized and tc_id:
            preview = event.data.get("result", "")
            original_length = event.data.get("original_length", 0)
            message_content = (
                preview + "\n\n"
                f"[结果已截断，完整结果共 {original_length} 字符。"
                f"使用 read_tool_result 工具并传入 tool_call_id={tc_id} 可获取完整结果。]"
            )
        else:
            message_content = full_result

        await self.agent_service.save_message(
            conversation_id=conv.id,
            role="tool",
            content=message_content,
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

    # ==================== 上下文自动压缩 ====================

    async def _compress_messages(
        self,
        messages: List[Dict],
        memory_manager: MemoryManager,
        model: str,
        context_window: int,
        conversation_id: int,
    ) -> List[Dict]:
        """将 OpenAI 格式消息压缩后返回（上下文溢出时调用）"""
        from novamind.features.agent.core.memory.interfaces import MemoryMessage
        from novamind.features.agent.core.memory.token_budget import TokenBudget

        # OpenAI dicts → MemoryMessage
        mem_msgs = []
        for m in messages:
            mem_msgs.append(MemoryMessage(
                role=m.get("role", "user"),
                content=m.get("content") or "",
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
                tool_name=m.get("name"),
            ))

        budget = TokenBudget(model)
        available = context_window - 4096  # 留出生成空间
        if available < 2000:
            return messages

        compressed, _, _ = await memory_manager._short_term._compression.compress(
            mem_msgs, available, budget, conversation_id=conversation_id,
        )

        # MemoryMessage → OpenAI dicts
        result = []
        for mm in compressed:
            d: Dict[str, Any] = {"role": mm.role}
            if mm.content:
                d["content"] = mm.content
            if mm.tool_calls:
                d["tool_calls"] = mm.tool_calls
                d["content"] = None  # assistant with tool_calls
            if mm.tool_call_id:
                d["tool_call_id"] = mm.tool_call_id
            if mm.tool_name:
                d["name"] = mm.tool_name
            result.append(d)

        return result

    # ==================== 工具方法 ====================

    def _format_sse(self, event_type: str, data: dict) -> str:
        """格式化 SSE 事件"""
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
