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

from novamind.core.ws import envelope
from novamind.shared.model_config_ports import ModelConfigPort
from novamind.features.agent.services.agent_service import AgentService
from novamind.engines.agent.agent_engine import AgentEngine, AgentEvent
from novamind.engines.agent.memory.memory_manager import MemoryManager
from novamind.engines.agent.memory.context_scrubber import StreamingContextScrubber
from novamind.engines.agent.prompt_builder import SystemPromptBuilder
from novamind.features.agent.repository.agent_repository import MessageRepository, ToolCallRepository, SessionRepository
from novamind.features.agent.repository.memory_search_repository import MemorySearchRepository
from novamind.features.agent.adapters import (
    HostKnowledgeSearchPort,
    HostMemorySearchPort,
    HostMemoryStorePort,
    HostPromptProvider,
    HostWebSearchPort,
)
from novamind.features.agent.models.agent import AgentDefinition
from novamind.features.agent.models.session import AgentSession
from novamind.features.agent.models.message import AgentMessage
from novamind.features.agent.exceptions import AgentError, AgentNotFoundError
from novamind.engines.agent.tool.base import ToolContext
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
        model_config_service: ModelConfigPort,
        agent_engine: AgentEngine,
        todo_store: Optional[Any] = None,
        memory_search_repo: Optional[MemorySearchRepository] = None,
        minio_client: Optional[Any] = None,
        memory_store_port: Optional[HostMemoryStorePort] = None,
        memory_search_port: Optional[HostMemorySearchPort] = None,
        knowledge_search_port: Optional[HostKnowledgeSearchPort] = None,
        web_search_port: Optional[HostWebSearchPort] = None,
        prompt_provider: Optional[HostPromptProvider] = None,
    ):
        self.db = db
        self.agent_service = agent_service
        self.model_config_service = model_config_service
        self.agent_engine = agent_engine
        self._todo_store = todo_store
        self._memory_search_repo = memory_search_repo
        self._minio_client = minio_client
        self._memory_store_port = memory_store_port
        self._memory_search_port = memory_search_port
        self._knowledge_search_port = knowledge_search_port
        self._web_search_port = web_search_port
        self._prompt_provider = prompt_provider
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
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行 Agent 对话，返回事件流（dict 事件，经 WS 推送）"""
        try:
            agent, conv, user_msg = await self._prepare(
                user_id, agent_id, content, session_id, llm_model, attachment_ids
            )

            yield self._emit("session", {
                "session_id": conv.session_id,
                "agent_id": agent_id,
            })

            # 解析模型（MemoryManager 和 LLM 客户端共用）
            model = await self._resolve_model(user_id, agent, llm_model)

            # 端口由装配点（get_agent_chat_service）注入，此处直接取用
            memory_store = self._memory_store_port
            memory_search = self._memory_search_port
            prompt_provider = self._prompt_provider
            knowledge_search_port = self._knowledge_search_port

            # 创建 MemoryManager（每请求实例）
            memory_manager = self._create_memory_manager(
                agent, user_id, model, conv.id,
                memory_store, memory_search, prompt_provider,
            )

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
            # 引擎端口注入（供 builtin 工具经 context 取用）
            # web_search_port：装配点已按数据库默认搜索引擎(is_primary)构造注入；
            # 仅当 Agent 勾选 web_search 工具时下发给引擎
            context["web_search_port"] = (
                self._web_search_port
                if "web_search" in (agent.enabled_tools or [])
                else None
            )
            context["knowledge_search_port"] = knowledge_search_port
            context["memory_store_port"] = memory_store
            context["memory_search_port"] = memory_search
            context["embedding_client_resolver"] = self._build_embedding_resolver(user_id)

            # E6 子 agent 委派：Agent 勾选 task 工具时注入 SubAgentRunner
            if "task" in (agent.enabled_tools or []):
                from novamind.engines.agent.subagent import SubAgentRunner

                context["subagent_runner"] = SubAgentRunner(
                    agent_engine=self.agent_engine,
                    tool_executor=self.agent_engine.tool_executor,
                    model_config_service=self.model_config_service,
                    user_id=user_id,
                    model=model,
                    enabled_tools=agent.enabled_tools or [],
                    enabled_mcp_ids=agent.enabled_mcp_servers or [],
                    parent_context=context,
                )
            else:
                context["subagent_runner"] = None

            full_response = ""
            full_reasoning = ""
            collected_sources: List[Dict[str, Any]] = []
            scrubber = StreamingContextScrubber()
            reasoning_scrubber = StreamingContextScrubber()

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
                    yield self._emit("tool_call", event.data)

                elif event.event_type == "tool_result":
                    await self._handle_tool_result(event, conv, context)
                    self._extract_sources(event, collected_sources)
                    yield self._emit("tool_result", event.data)

                elif event.event_type == "reasoning":
                    raw_r = event.data.get("content", "")
                    cleaned_r = reasoning_scrubber.feed(raw_r)
                    full_reasoning += cleaned_r
                    if cleaned_r:
                        yield self._emit("reasoning", {"content": cleaned_r})

                elif event.event_type == "content":
                    raw_content = event.data.get("content", "")
                    cleaned = scrubber.feed(raw_content)
                    full_response += cleaned
                    if cleaned:
                        yield self._emit("content", {"content": cleaned})

                elif event.event_type == "done":
                    # flush scrubber buffer
                    remaining = scrubber.flush()
                    if remaining:
                        full_response += remaining
                    remaining_r = reasoning_scrubber.flush()
                    if remaining_r:
                        full_reasoning += remaining_r
                    if event.data.get("truncated", False):
                        full_response += "\n\n[Agent 已达到最大迭代次数，对话被截断]"
                    # 发送结构化来源引用（对齐 QA sources 事件）
                    if collected_sources:
                        yield self._emit("sources", {"sources": collected_sources})
                    done_data = await self._handle_done(
                        event, conv, content, full_response,
                        reasoning=full_reasoning or None,
                        sources=collected_sources or None,
                    )
                    # E1 可观测性：done 加 cost_usd + 写 agent_usage 表
                    done_data = await self._record_usage(
                        done_data, user_id, conv, agent_id, model
                    )
                    yield self._emit("done", done_data)

                elif event.event_type == "error":
                    yield self._emit("error", event.data)

                elif event.event_type == "context_overflow":
                    logger.warning("上下文溢出，建议压缩", conversation_id=conv.id)
                    yield self._emit("error", {"content": "对话上下文过长，请开启新会话或缩短对话历史"})

        except AgentNotFoundError:
            yield self._emit("error", {"content": "Agent 不存在"})
        except (asyncio.CancelledError, GeneratorExit):
            # 客户端断连（WS close）→ run_stream_to_ws aclose 触发；回滚未提交事务，
            # assistant 消息不落库（user 消息已在 _prepare 提交）
            conv_id = conv.id if "conv" in locals() else None
            logger.info("Agent 对话被客户端取消", conversation_id=conv_id)
            try:
                await self.db.rollback()
            except Exception as rollback_err:
                logger.warning("取消时事务回滚失败", error=str(rollback_err))
            raise
        except Exception as e:
            logger.error("Agent 对话失败", error=str(e))
            try:
                await self.db.rollback()
            except Exception as rollback_err:
                logger.warning("事务回滚失败", error=str(rollback_err))
            yield self._emit("error", {"content": f"对话失败：{str(e)}"})

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
        self,
        agent: AgentDefinition,
        user_id: int,
        model: str,
        conversation_id: int,
        memory_store: HostMemoryStorePort,
        memory_search: Optional[HostMemorySearchPort],
        prompt_provider: HostPromptProvider,
    ) -> MemoryManager:
        """创建请求级 MemoryManager 实例（端口由 chat_stream 注入）"""
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
            long_term_store=memory_store,
            summary_store=memory_store,
            prompt_provider=prompt_provider,
            model=model,
            llm_client_factory=llm_factory,
            memory_search=memory_search,
            embedding_factory=embedding_factory if memory_search else None,
            todo_store=self._todo_store,
            conversation_id=conversation_id,
            agent_id=agent.id,
            user_id=user_id,
            auxiliary_llm_factory=auxiliary_llm_factory,
        )

    def _build_embedding_resolver(self, user_id: int):
        """构造 embedding 客户端 resolver（供 memory 工具 _index_to_es 经
        context["embedding_client_resolver"] 调用，与 MemoryManager 的
        embedding_factory 同源）。"""
        async def resolver():
            embedding_model = await self.model_config_service.get_user_default_model_name(
                user_id, "embedding"
            )
            if not embedding_model:
                raise RuntimeError("未配置 embedding 模型")
            return await self.model_config_service.get_embedding_client_by_model(
                user_id, embedding_model
            )
        return resolver

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

    # ==================== 来源提取 ====================

    def _extract_sources(
        self, event: AgentEvent, collected_sources: List[Dict[str, Any]]
    ) -> None:
        """从 tool_result 事件中提取结构化来源引用（对齐 QA SourceRef）。"""
        tool_name = event.data.get("tool_name", "")
        result_str = event.data.get("result", "")
        if not result_str:
            return

        try:
            result_obj = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            return

        if tool_name == "web_search":
            items = result_obj.get("results", [])
            if not isinstance(items, list):
                return
            start_idx = len(collected_sources)
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                collected_sources.append({
                    "index": start_idx + i + 1,
                    "kind": "web",
                    "document_name": str(item.get("title", "") or ""),
                    "url": str(item.get("url", "") or ""),
                    "snippet": str(item.get("snippet", "") or ""),
                })
        elif tool_name == "knowledge_search":
            items = result_obj.get("results", [])
            if not isinstance(items, list):
                return
            start_idx = len(collected_sources)
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                fi = item.get("file_info") or {}
                metadata = item.get("metadata") or {}
                collected_sources.append({
                    "index": start_idx + i + 1,
                    "kind": "kb",
                    "document_id": item.get("document_id"),
                    "document_name": str(fi.get("filename", "") or ""),
                    "chunk_id": item.get("chunk_id") or metadata.get("chunk_id"),
                    "score": item.get("score"),
                    "snippet": str(item.get("content", "") or "")[:500],
                })

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
        reasoning: Optional[str] = None,
        sources: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """处理 done 事件：保存 assistant 消息、更新统计、设置标题"""
        total_tokens = event.data.get("total_tokens", 0)

        assistant_msg = await self.agent_service.save_message(
            conversation_id=conv.id,
            role="assistant",
            content=full_response,
            token_count=total_tokens,
            reasoning=reasoning,
        )

        await self.agent_service.update_session_stats(conv.id, total_tokens)

        # 更新会话标题
        await self.db.refresh(conv)
        if conv.message_count <= 1 and not conv.title:
            title = user_content[:50] + ("..." if len(user_content) > 50 else "")
            await self.session_repo.update(conv.id, title=title)

        await self.db.commit()

        event.data["message_id"] = assistant_msg.id
        if sources:
            event.data["sources"] = sources
        return event.data

    async def _record_usage(
        self,
        done_data: Dict[str, Any],
        user_id: int,
        conv: AgentSession,
        agent_id: int,
        model: str,
    ) -> Dict[str, Any]:
        """E1 可观测性：done_data 加 cost_usd + 写 agent_usage 表。

        失败不阻断对话（仅 warning 日志）。
        """
        usage_breakdown = done_data.get("usage_breakdown") or {}
        if not usage_breakdown:
            return done_data
        try:
            from novamind.shared.ai_models.usage import CanonicalUsage, estimate_cost
            from novamind.features.agent.repository.agent_usage_repository import (
                AgentUsageRepository,
            )

            usage = CanonicalUsage(
                input_tokens=usage_breakdown.get("input_tokens", 0),
                output_tokens=usage_breakdown.get("output_tokens", 0),
                cache_read_tokens=usage_breakdown.get("cache_read_tokens", 0),
                cache_write_tokens=usage_breakdown.get("cache_write_tokens", 0),
                reasoning_tokens=usage_breakdown.get("reasoning_tokens", 0),
            )
            cost = estimate_cost(usage, model)
            done_data["cost_usd"] = float(cost)

            usage_repo = AgentUsageRepository(self.db)
            await usage_repo.log_usage(
                user_id=user_id,
                session_id=conv.session_id,
                conversation_id=conv.id,
                agent_id=agent_id,
                model=model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                total_tokens=usage.total_tokens,
                cost_usd=cost,
                iterations=done_data.get("iterations", 0),
                tool_calls_count=done_data.get("tool_calls_count", 0),
            )
        except Exception as e:
            logger.warning("agent_usage 记录失败", error=str(e))
        return done_data

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
        from novamind.engines.agent.memory.interfaces import MemoryMessage
        from novamind.engines.agent.memory.token_budget import TokenBudget

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

    def _emit(self, event_type: str, data: dict) -> dict:
        """构造统一事件 envelope（WS 推送用，取代 SSE 帧）"""
        return envelope(event_type, data)
