"""上下文组装 mixin：会话准备/模型解析/三层记忆/提示词构建/附件清单/图片注入（纯搬移自 chat_service）。

依赖主类属性：self.db/self.logger/self.attachment_repo/self.ports_*；
类级 _PROMPT_CACHE/_CACHE_TTL/_CLASS_CACHE_MAX 定义在主类，经 cls 从 MRO 可达。
"""
import base64
from time import monotonic
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.agent.memory.interfaces import MemorySnapshot
from novamind.engines.agent.memory.memory_manager import MemoryManager
from novamind.features.agent.exceptions import (
    AgentError,
)
from novamind.features.agent.models.agent import AgentDefinition
from novamind.features.agent.models.message import AgentMessage
from novamind.features.agent.models.session import AgentSession
from novamind.features.agent.schemas.agent_schema import (
    ContextUsageResponse,
    SystemPromptResponse,
)
from novamind.features.agent.services.context_assembly import (
    filter_visible_mcp_ids,
)
from novamind.features.agent.services.host_memory_store import (
    HostMemorySearchPort,
    HostMemoryStorePort,
)
from novamind.features.agent.tool.builtins.plan_output import PlanOutputTool
from novamind.shared.ai_models.base_model import LLMCapabilities, resolve_capabilities
from novamind.shared.prompts.prompt_manager import PromptManager
from novamind.shared.utils.time_utils import now_china

logger = get_logger(__name__)


class ChatContextBuilderMixin:
    """上下文组装 mixin：会话准备/模型解析/三层记忆/提示词构建/附件清单/图片注入（纯搬移自 chat_service）。"""

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _prepare(
        self,
        user_id: int,
        agent_id: int,
        content: str,
        session_id: str | None,
        llm_model: str | None,
        attachment_ids: list[int] | None = None,
    ) -> tuple[AgentDefinition, AgentSession, AgentMessage]:
        """准备阶段：获取 Agent、创建/恢复会话、保存用户消息（消毒后 content + extra）"""
        agent = await self.agent_service.get_agent_definition(user_id, agent_id)

        conv = await self.agent_service.get_or_create_session(
            user_id, agent_id, session_id
        )

        # 解析附件，构造 extra（不修改 content）
        extra = None
        if attachment_ids:
            attachments = await self.attachment_repo.get_by_ids_and_user(attachment_ids, user_id)
            if attachments:
                from novamind.shared.message_attachments import write_attachment_ids
                extra = write_attachment_ids(None, [
                    {"id": a.id, "filename": a.filename, "file_type": a.file_type, "file_size": a.file_size, "storage_path": a.storage_path}
                    for a in attachments
                ])

        # 写入时消毒（prompt 注入防护唯一入口）：转义 '<' 防伪造系统标签 +
        # 旧版裸 compaction 前缀降格。DB 存安全形态，此后上下文组装/压缩序列化/
        # 历史回放零变换——消息字节从第一轮起恒定，prompt cache 前缀稳定由构造保证。
        from novamind.engines.agent.memory.short_term import sanitize_user_content
        safe_content = sanitize_user_content(content)

        user_msg = await self.agent_service.save_message(
            conversation_id=conv.id,
            role="user",
            content=safe_content,
            extra=extra,
        )

        return agent, conv, user_msg

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _resolve_model(
        self, user_id: int, agent: AgentDefinition, llm_model: str | None
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

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _create_memory_manager(
        self,
        agent: AgentDefinition,
        user_id: int,
        model: str,
        conversation_id: int,
        memory_store: HostMemoryStorePort,
        memory_search: HostMemorySearchPort | None,
        prompt_provider: PromptManager,
    ) -> MemoryManager:
        """创建请求级 MemoryManager 实例（装配收口在 memory_assembly，此为薄委托）。

        供 chat_stream / estimate_context_usage / get_system_prompt 与群聊
        fork（GroupOrchestrator._fork_runtime）调用——群聊场景 self 已是
        fork 实例，仓储随 self.db 绑定到分身会话。
        """
        from novamind.features.agent.services.memory_assembly import create_memory_manager

        return await create_memory_manager(
            self.db, self.model_config_service,
            agent=agent, user_id=user_id, model=model,
            conversation_id=conversation_id,
            memory_store=memory_store, memory_search=memory_search,
            prompt_provider=prompt_provider, todo_store=self._todo_store,
        )

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _build_context(
        self,
        agent: AgentDefinition,
        conv: AgentSession,
        user_id: int,
        model: str,
        user_content: str,
        memory_manager: MemoryManager,
        dry_run: bool = False,
        deep_research: bool = False,
    ) -> tuple[Any, list[dict], list[dict], MemorySnapshot, str, LLMCapabilities]:
        """构建阶段：获取 LLM 客户端、工具列表、上下文消息（三层记忆）。

        dry_run=True 时只算 token 不触发压缩、不写 summary，prefetch 不计
        access_count、图片不做 MinIO 下载，用于历史会话初始 context_usage 估算
        （ContextMeter）。

        Returns:
            (llm_client, tools, messages, snapshot, system_prompt, caps)。
            caps 为模型生效能力集，供调用侧协商 plan_mode/thinking 透传。
        """
        # LLM 客户端（优先 LLM 类型，fallback 到 VLM 类型）
        try:
            llm_client = await self.model_config_service.get_llm_client_by_model(
                user_id, model
            )
        except Exception:
            llm_client = await self.model_config_service.get_vlm_client_by_model(
                user_id, model
            )

        # 能力协商：模型不支持工具时跳过辅助工具注入（无工具路径经 BaseLLM
        # 委托纯文本方法，任何协议都可用）；enabled_tools 非空时降级提示词模拟
        caps = resolve_capabilities(llm_client)

        # 工具列表
        tool_executor = self.agent_engine.tool_executor
        enabled_tools = list(agent.enabled_tools or [])
        # 工作模式（会话绑定工作区）默认必带六件套：后端强制并入 local_workspace
        # 勾选，不依赖前端——绑定本身即授权（dsh workspace-write 同语义）
        ws_cfg = (conv.extra_config or {}).get("workspace") or {}
        if ws_cfg.get("mode") == "local" and ws_cfg.get("root"):
            if "local_workspace" not in enabled_tools:
                enabled_tools.append("local_workspace")
        # 归属过滤：他人私有 MCP 服务器不可借用（含其凭证），剔除并告警不抛错
        enabled_mcp_ids = await filter_visible_mcp_ids(
            self.db, user_id, agent.enabled_mcp_servers or []
        )
        tools = (
            tool_executor.resolve_tools_openai_format(enabled_tools, enabled_mcp_ids)
            if caps.tools
            else []
        )

        # 自动注入 read_tool_result 工具（始终可用，不受 enabled_tools 限制）
        if caps.tools and not any(
            t.get("function", {}).get("name") == "read_tool_result" for t in tools
        ):
            try:
                read_tool_def = tool_executor._resolve_tool_definition("read_tool_result")
                if read_tool_def:
                    tools.append(read_tool_def.to_openai_format())
            except Exception:
                pass

        # 自动注入 read_attachment 工具（始终可用）：附件正文不注入上下文，
        # 上下文里只有 <system-uploaded-files> 清单，模型经本工具按 offset/limit 分片读取
        if caps.tools and not any(
            t.get("function", {}).get("name") == "read_attachment" for t in tools
        ):
            try:
                read_att_def = tool_executor._resolve_tool_definition("read_attachment")
                if read_att_def:
                    tools.append(read_att_def.to_openai_format())
            except Exception:
                pass

        # 计划模式注入 plan_output 工具：各步产出上下文里只有头尾节选，
        # 模型经本工具按步骤号回查落库全文（非计划模式不注入，防止误用）
        if caps.tools:
            self._inject_plan_output_tool(tools, agent)

        # 工作模式：工作目录以 user-role 运行时快照注入（dsh 同款——不入
        # 按 agent 冻结的 prompt 缓存，会话内路径恒定不撕裂 KV cache）
        workspace_prompt = ""
        if ws_cfg.get("mode") == "local" and ws_cfg.get("root"):
            workspace_prompt = (
                f'Current working directory: "{ws_cfg["root"]}"\n'
                "(All workspace tool paths are relative to this directory.)"
            )

        # 构建系统提示词（分层组装 + 缓存）
        formatted_prompt = self._format_base_prompt(agent.system_prompt, enabled_tools)
        # 快照护栏 = 窗口×20%，与 prompt_builder 分层丢弃阈值同口径；会话粒度冻结
        frozen_memory = await self._get_frozen_memory(
            memory_manager, agent.id, user_id, conv.id,
            max_tokens=int((agent.context_window or 32768) * 0.20),
        )

        # cache key 纳入能力标记：同 agent 换模型（能力面不同 → 提示词不同）不串缓存
        cache_key = f"{agent.id}:{frozenset(enabled_tools)}:{model}:tools={caps.tools}"
        cached_partial = self._get_cached_prompt(cache_key)

        if cached_partial is None:
            skill_fragments = await self._collect_skill_fragments(enabled_tools)
            cached_partial = await self._prompt_builder.build(
                base_prompt=formatted_prompt,
                enabled_tools=enabled_tools if caps.tools else [],
                skill_fragments=skill_fragments,
                frozen_memory="",
                model_name=model,
                max_prompt_tokens=agent.context_window,
            )
            self._set_cached_prompt(cache_key, cached_partial)

        if caps.tools:
            tail_parts = [p for p in (frozen_memory, workspace_prompt) if p]
            system_prompt = cached_partial + ("\n\n" + "\n\n".join(tail_parts) if tail_parts else "")
        else:
            # 无工具能力的模型：诚实声明工具不可执行（防正文假调用被误解为已执行），
            # 引导模型基于上下文直接回答
            sim_block = self._build_tool_simulation_block(agent, enabled_tools)
            parts = [cached_partial]
            if frozen_memory:
                parts.append(frozen_memory)
            if workspace_prompt:
                parts.append(workspace_prompt)
            if sim_block:
                parts.append(sim_block)
            system_prompt = "\n\n".join(parts)

        # 记忆预取（计量前串行 await：overlays 进 build_context 计入预算；
        # dry_run 不计 access_count，估算无副作用）
        relevant = await memory_manager.prefetch(
            user_content, agent.id, user_id, count_access=not dry_run
        )

        # 附件清单纯构建（只读 DB，dry_run 也执行使仪表估算完整；
        # dry_run 不下载图片——MinIO IO 是副作用）
        is_vlm = await self._is_vlm_model(model, user_id)
        manifest, overlay_img_parts = await self._build_attachment_manifest(
            conv.id, user_id, is_vlm, download_images=not dry_run
        )

        # overlays 叠放规范（top→bottom）：参考数据在上、行为指令贴近用户内容。
        # 全部进 build_context 计量前注入，计入 token 预算与压缩判定
        overlays: list[str] = []
        if relevant:
            overlays.append(self._build_memory_overlay(relevant))
        if manifest:
            overlays.append(manifest)
        if deep_research:
            overlays.append(self.RESEARCH_MODE_HINT)

        snapshot = await memory_manager.build_context(
            system_prompt=system_prompt,
            conversation_id=conv.id,
            max_tokens=agent.context_window or 32768,
            tools=tools,
            dry_run=dry_run,
            user_overlays=overlays or None,
        )

        if snapshot.compressed:
            logger.info(
                "上下文已压缩",
                conversation_id=conv.id,
                compression_ratio=snapshot.compression_ratio,
                tokens=snapshot.total_tokens,
            )

        # 本轮图片：多模态 content 注入（非文本 overlay），在 build_context 之后
        # 附加到最后一条 user 消息（图片 token 走 85/张近似口径，不经文本计量）
        if not dry_run:
            self._inject_current_images(snapshot, overlay_img_parts)

        return llm_client, tools, snapshot.messages, snapshot, system_prompt, caps

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    @staticmethod
    def _build_tool_simulation_block(
        agent: AgentDefinition, enabled_tools: list[str]
    ) -> str:
        """构造无工具模型的提示词模拟块：诚实声明不可执行，仅列能力意图。

        文案必须明确「不可执行」——否则模型在正文输出形似工具调用的文本，
        用户会误以为已执行（失败方向安全：宁可少能力，不出错误结果）。

        Args:
            agent: Agent 定义（未使用参数保留签名对称性）。
            enabled_tools: Agent 勾选的工具名列表。

        Returns:
            提示词模拟块文本；Agent 未勾选任何工具时返回空串（无必要声明）。
        """
        if not enabled_tools:
            return ""
        tool_list = "\n".join(f"- {name}" for name in enabled_tools)
        return (
            "<system-tool-simulation>\n"
            "当前所配置的模型不支持工具调用（function calling）。以下工具在本会话中不可执行：\n"
            f"{tool_list}\n\n"
            "请基于已有上下文直接回答用户问题。若任务必须依赖上述工具才能完成，"
            "请如实告知用户当前模型不支持该操作，不要在回答中输出任何形似工具调用的内容。"
            "</system-tool-simulation>"
        )

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def estimate_context_usage(
        self, user_id: int, session_id: str
    ) -> ContextUsageResponse:
        """历史会话初始上下文用量估算（ContextMeter 历史回放）。

        复用 _build_context(dry_run=True)：只算 system/tools/messages token 分项，
        不触发压缩、不写 summary、跳过 prefetch/附件副作用。口径与实时 context_usage
        事件一致，前端切历史会话即可显示仪表初始值。
        """
        conv = await self.agent_service.get_session(user_id, session_id)
        agent = await self.agent_service.get_agent_or_fail(user_id, conv.agent_id)
        model = await self._resolve_model(user_id, agent, None)
        memory_manager = await self._create_memory_manager(
            agent, user_id, model, conv.id,
            self._memory_store_port, self._memory_search_port, self._prompt_provider,
        )
        _, _, _, snapshot, _, _ = await self._build_context(
            agent, conv, user_id, model, "", memory_manager, dry_run=True
        )
        return ContextUsageResponse(
            used_tokens=snapshot.total_tokens,
            context_window=snapshot.context_window,
            system_tokens=snapshot.system_tokens,
            tools_tokens=snapshot.tools_tokens,
            messages_tokens=snapshot.messages_tokens,
            reserved_tokens=snapshot.reserved_tokens,
            compressed=snapshot.compressed,
            compression_ratio=snapshot.compression_ratio,
        )

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def get_system_prompt(
        self, user_id: int, session_id: str
    ) -> SystemPromptResponse:
        """返回会话当前 system prompt 全文（轨迹视图 inspector 展开 system 行按需拉）。

        复用 _build_context 的 system_prompt 构造逻辑（base + tool guidance + skill
        fragments + frozen_memory），与实际发给 LLM 的 system prompt 一致。
        """
        conv = await self.agent_service.get_session(user_id, session_id)
        agent = await self.agent_service.get_agent_or_fail(user_id, conv.agent_id)
        model = await self._resolve_model(user_id, agent, None)
        memory_manager = await self._create_memory_manager(
            agent, user_id, model, conv.id,
            self._memory_store_port, self._memory_search_port, self._prompt_provider,
        )
        enabled_tools = list(agent.enabled_tools or [])
        # 与 _build_context 同口径：工作模式强制并入 local_workspace
        ws_cfg = (conv.extra_config or {}).get("workspace") or {}
        if ws_cfg.get("mode") == "local" and ws_cfg.get("root"):
            if "local_workspace" not in enabled_tools:
                enabled_tools.append("local_workspace")
        formatted_prompt = self._format_base_prompt(agent.system_prompt, enabled_tools)
        # 快照护栏 = 窗口×20%，与 prompt_builder 分层丢弃阈值同口径；会话粒度冻结
        frozen_memory = await self._get_frozen_memory(
            memory_manager, agent.id, user_id, conv.id,
            max_tokens=int((agent.context_window or 32768) * 0.20),
        )
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
        parts = [cached_partial]
        if frozen_memory:
            parts.append(frozen_memory)
        # 工作目录快照（与实时路径一致，轨迹 inspector 展示的 prompt 即实发 prompt）
        if ws_cfg.get("mode") == "local" and ws_cfg.get("root"):
            parts.append(
                f'Current working directory: "{ws_cfg["root"]}"\n'
                "(All workspace tool paths are relative to this directory.)"
            )
        system_prompt = "\n\n".join(parts)
        from novamind.engines.agent.memory.token_budget import TokenBudget
        tokens = TokenBudget(model).count_text_tokens(system_prompt)
        return SystemPromptResponse(system_prompt=system_prompt, tokens=tokens)

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    @staticmethod
    def _inject_plan_output_tool(tools: list, agent: Any) -> None:
        """计划模式自动注入 plan_output 工具（原地追加，去重防御）。

        各步产出的上下文注入只有头尾节选（planning_flow._bound_step_output），
        本工具让模型按步骤号回查落库全文；非计划模式不注入防止误用。
        """
        if not bool((agent.extra_config or {}).get("plan_mode")):
            return
        if any(t.get("function", {}).get("name") == "plan_output" for t in tools):
            return
        try:
            tool_def = PlanOutputTool().get_tools()[0]
            tools.append(tool_def)
        except Exception as e:
            logger.warning("plan_output 工具注入失败", error=str(e))

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    def _format_base_prompt(self, system_prompt: str, enabled_tools: list) -> str:
        """格式化基础提示词中的占位符"""
        if "{tools}" not in system_prompt:
            return system_prompt
        tool_names = ", ".join(enabled_tools) if enabled_tools else "无"
        try:
            return system_prompt.format(
                tools=tool_names,
                current_date=now_china().strftime("%Y-%m-%d"),
            )
        except (KeyError, IndexError, ValueError):
            # 用户自定义 system_prompt 含其它 {...} 字面量（如 JSON 示例/代码模板）时
            # str.format 会 KeyError——降级为只替换两个已知占位符，不因模板写法
            # 让该 agent 全部对话 500
            return (
                system_prompt
                .replace("{tools}", tool_names)
                .replace("{current_date}", now_china().strftime("%Y-%m-%d"))
            )

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _get_frozen_memory(
        self,
        memory_manager: MemoryManager,
        agent_id: int,
        user_id: int,
        conversation_id: int,
        max_tokens: int | None = None,
    ) -> str:
        """获取长期记忆冻结快照（类级缓存，会话粒度冻结 + 滑动 TTL 续期）。

        冻结语义：快照按会话首请求时点冻结，会话期间字节恒定——记忆写入
        （consolidate/memory 工具）不使当前会话的 system prompt 变化，
        前缀 KV cache 不因 TTL 过期被撕裂；新记忆在下个会话进入快照。
        读命中滑动续期（活跃会话任意时长内恒定，停止访问 300s 后过期回收）。
        MemoryManager 实例级的 _frozen_snapshot_cache 因每请求新建从未生效，
        此处类级缓存才是真正的冻结层。

        conversation_id 与 max_tokens 都进缓存键：前者划定冻结边界，后者
        避免不同护栏串缓存。
        """
        cache_key = f"fm:{agent_id}:{user_id}:{conversation_id}:{max_tokens}"
        cached = self._get_class_cached(self._FROZEN_MEMORY_CACHE, cache_key, sliding=True)
        if cached is not None:
            return cached
        try:
            snapshot = (
                await memory_manager.build_frozen_snapshot(agent_id, user_id, max_tokens)
                or ""
            )
        except Exception as e:
            logger.warning("冻结快照加载失败", error=str(e))
            return ""
        self._set_class_cached(self._FROZEN_MEMORY_CACHE, cache_key, snapshot)
        return snapshot

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    @classmethod
    def _get_class_cached(cls, cache: dict, key: str, sliding: bool = False) -> str | None:
        """读类级 TTL 缓存，过期即删并返回 None。

        sliding=True 时读命中刷新时间戳（活跃会话无限续期，停止访问后
        TTL 自然过期回收）——frozen_memory 专用：会话任意时长内快照字节
        恒定，前缀 KV cache 不因 TTL 边界被撕裂。_PROMPT_CACHE 保持固定
        TTL：滑动续期会让高频 agent 的技能更新永不生效。
        """
        entry = cache.get(key)
        if entry is None:
            return None
        prompt, ts = entry
        now = monotonic()
        if now - ts < cls._CACHE_TTL:
            if sliding:
                cache[key] = (prompt, now)
            return prompt
        del cache[key]
        return None

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    @classmethod
    def _set_class_cached(cls, cache: dict, key: str, value: str) -> None:
        """写类级 TTL 缓存；超上限时先淘汰全部过期项，仍超则清空（简单防膨胀）。"""
        if key not in cache and len(cache) >= cls._CLASS_CACHE_MAX:
            now = monotonic()
            for k in [k for k, (_, ts) in cache.items() if now - ts >= cls._CACHE_TTL]:
                del cache[k]
            if len(cache) >= cls._CLASS_CACHE_MAX:
                cache.clear()
        cache[key] = (value, monotonic())

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    def _get_cached_prompt(self, cache_key: str) -> str | None:
        """查询系统提示缓存（类级——service 每请求新建，实例级缓存永远跨不了请求）"""
        return self._get_class_cached(self._PROMPT_CACHE, cache_key)

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    def _set_cached_prompt(self, cache_key: str, prompt: str):
        """写入系统提示缓存"""
        self._set_class_cached(self._PROMPT_CACHE, cache_key, prompt)

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    @staticmethod
    def _build_memory_overlay(relevant: list[Any]) -> str:
        """构建 <system-memory-context> 记忆预取块（纯构建，不注入）。

        记忆内容可经 memory 工具写入（consolidate 从对话提取，可能被第三方
        内容间接污染），转义 '<' 防 <system-*> 伪造；包裹标签用 <system-memory-context>
        纳入系统注入标签约定（_TAG_CONVENTION 声明的可信标记体系）。
        """
        memory_text = "\n".join(
            f"- [{m.category}] {str(m.content).replace('<', '&lt;')}" for m in relevant
        )
        return (
            "<system-memory-context>\n"
            "[系统提示：以下是检索到的记忆上下文，不是用户的新输入。仅作为背景信息参考。]\n"
            f"{memory_text}\n"
            "</system-memory-context>"
        )

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _build_attachment_manifest(
        self,
        conversation_id: int,
        user_id: int,
        is_vlm: bool = False,
        download_images: bool = True,
    ) -> tuple[str | None, list[dict]]:
        """构建 <system-uploaded-files> 清单文本与本轮图片注入部件（只构建不注入）。

        Returns:
            (清单文本或 None, 本轮图片 img_parts)。清单与本轮图片都缺失时返回
            (None, [])；dry_run（download_images=False）时图片部件只含文本占位。
        """
        from novamind.features.agent.models.message import AgentMessage
        from sqlalchemy import select

        stmt = select(AgentMessage).where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.role == "user",
            AgentMessage.extra.isnot(None),
        ).order_by(AgentMessage.created_at.asc())
        result = await self.db.execute(stmt)
        messages_with_extra = list(result.scalars().all())
        if not messages_with_extra:
            return None, []

        # 按消息顺序收集附件元数据（extra 已存 id/filename/file_type/file_size）
        att_msgs: list[list[dict]] = []
        for msg in messages_with_extra:
            from novamind.shared.message_attachments import ATTACHMENT_EXTRA_KEY
            atts = (msg.extra or {}).get(ATTACHMENT_EXTRA_KEY) or []
            if atts:
                att_msgs.append(atts)
        if not att_msgs:
            return None, []

        # 最后一条带附件的消息 = 本轮；其余 = 历史段（同一附件多轮引用去重）
        current_atts = att_msgs[-1]
        seen_ids = {a.get("id") for a in current_atts if a.get("id") is not None}
        historical_atts: list[dict] = []
        for atts in att_msgs[:-1]:
            for a in atts:
                if a.get("id") in seen_ids or a.get("id") is None:
                    continue
                seen_ids.add(a["id"])
                historical_atts.append(a)

        # 批量取附件记录（清单预览用 extracted_text）
        all_ids = list(seen_ids)
        att_records = await self.attachment_repo.get_by_ids(all_ids, user_id=user_id)
        att_by_id = {a.id: a for a in att_records}

        def _is_image(a: dict) -> bool:
            return (a.get("file_type") or "") in self.IMAGE_TYPES

        # 清单分段：本轮文档 / 历史文档（图片不进清单，本轮图片单独注入）
        current_docs = [a for a in current_atts if not _is_image(a)]
        current_imgs = [a for a in current_atts if _is_image(a)]
        historical_docs = [a for a in historical_atts if not _is_image(a)]

        doc_sections = [
            ("本轮上传的文件：", current_docs),
            ("之前轮次上传的文件（仍然可用）：", historical_docs),
        ]

        # <system-uploaded-files> 纳入系统注入标签约定；文件名与内容预览来自
        # 上传文件（extracted_text 可被文档内埋的指令污染），转义 '<' 防
        # 伪造清单边界或 <system-*> 注入
        lines = ["<system-uploaded-files>"]
        has_any = False
        for section_title, atts in doc_sections:
            if not atts:
                continue
            has_any = True
            lines.append(section_title)
            selected = atts[: self.MANIFEST_MAX_FILES_PER_SECTION]
            omitted = atts[self.MANIFEST_MAX_FILES_PER_SECTION :]
            for a in selected:
                rec = att_by_id.get(a.get("id"))
                size = a.get("file_size") or (rec.file_size if rec else 0) or 0
                size_str = (
                    f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"
                )
                filename = str(a.get("filename") or "").replace("<", "&lt;")
                lines.append(f"- {filename} ({size_str}) [attachment_id={a.get('id')}]")
                if rec and rec.extracted_text:
                    preview = rec.extracted_text[: self.MANIFEST_PREVIEW_CHARS].strip()
                    lines.append(f"  内容预览：{preview.replace('<', '&lt;')}")
                else:
                    lines.append("  （无可提取文本）")
            if omitted:
                lines.append(
                    f"  ...（另有 {len(omitted)} 个文件未列出，请基于已列出的文件回答）"
                )
        if not has_any and not current_imgs:
            return None, []  # 无文档类附件且无图片，无需清单

        lines.append("如需读取文件内容，使用 read_attachment 工具：")
        lines.append(
            "- read_attachment(attachment_id=..., offset=0, limit=8000) 分片读取；"
            "has_more=true 时以 offset += limit 继续"
        )
        lines.append("- 优先读取与当前问题相关的文件，不要一次性读取全部文件")
        lines.append("</system-uploaded-files>")
        manifest = "\n".join(lines)

        # 本轮图片：保持实时注入（VLM base64 / 非 VLM 文本占位）
        img_parts: list[dict] = []
        if current_imgs:
            if is_vlm and self._minio_client and download_images:
                for a in current_imgs:
                    rec = att_by_id.get(a.get("id"))
                    if rec is None:
                        continue
                    try:
                        b64_data = await self._download_attachment_as_base64(rec)
                        if b64_data:
                            mime = f"image/{rec.file_type}"
                            img_parts.append({
                                "type": "text",
                                "text": f"[图片: {str(rec.filename or '').replace('<', '&lt;')}]",
                            })
                            img_parts.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64_data}"},
                            })
                    except Exception as e:
                        logger.warning("图片下载失败，跳过", filename=rec.filename, error=str(e))
                        img_parts.append({
                            "type": "text",
                            "text": f"[图片: {str(rec.filename or '').replace('<', '&lt;')}（加载失败）]",
                        })
            else:
                for a in current_imgs:
                    img_parts.append({
                        "type": "text",
                        # filename 来自上传文件（可含标签样文本），转义 '<'
                        # 与清单字段同款防御
                        "text": (
                            f"[图片: {str(a.get('filename') or '').replace('<', '&lt;')}"
                            "（当前模型不支持视觉，无法查看）]"
                        ),
                    })

        return manifest, img_parts

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    @staticmethod
    def _inject_current_images(snapshot, img_parts: list[dict]) -> None:
        """把本轮图片部件（多模态 content）附加到最后一条 user 消息。

        与文本 overlays（计量前注入）不同：图片是消息 content 的多模态部分，
        在 build_context 之后附加，token 走 85/张近似口径不在文本计量内。
        """
        if not img_parts:
            return
        for msg in reversed(snapshot.messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                parts: list[dict] = list(img_parts)
                parts.append({"type": "text", "text": content})
                msg["content"] = parts
            elif isinstance(content, list):
                msg["content"] = list(img_parts) + list(content)
            else:
                logger.warning(
                    "用户消息 content 类型不支持图片注入",
                    content_type=type(content).__name__,
                )
            break

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _is_vlm_model(self, model_name: str, user_id: int) -> bool:
        """判断模型是否为 VLM 视觉模型"""
        try:
            vlm_models = await self.model_config_service.list_available_models(
                user_id, "vlm"
            )
            return model_name in vlm_models
        except Exception:
            return False

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _download_attachment_as_base64(self, attachment) -> str | None:
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

    # ---- 纯搬移自 chat_service.AgentChatService（勿原地修改语义） ----
    async def _collect_skill_fragments(self, enabled_tools: list) -> list:
        """收集技能广场中已安装技能的 Markdown 指令片段"""
        from novamind.features.skill.models.skill import ReviewStatus, SkillStatus

        fragments = []
        for skill_ref in enabled_tools:
            if not skill_ref.startswith("skill__"):
                continue
            try:
                # 格式: skill__{id}_{name}；name 可含下划线/连字符，须先剥前缀再按首个 _ 切
                body = skill_ref[len("skill__"):]
                parts = body.split("_", 1)
                if len(parts) < 2:
                    continue
                skill_id = int(parts[0])
                from novamind.features.skill.repository.skill_repository import SkillRepository
                repo = SkillRepository(self.db)
                skill_def = await repo.get_by_id(skill_id)
                if (
                    skill_def
                    and skill_def.body_markdown
                    and skill_def.status == SkillStatus.PUBLISHED
                    and skill_def.review_status == ReviewStatus.APPROVED
                ):
                    # 技能片段直拼 system prompt（PUBLISHED+APPROVED 门禁之外无
                    # 内容消毒）——转义 <system- 前缀防审核漏过的伪标签伪造
                    # 系统注入边界；display_name 同理
                    from novamind.shared.prompts.sanitize import escape_system_tags

                    fragments.append(
                        f"## 技能: {escape_system_tags(skill_def.display_name)}\n\n"
                        f"{escape_system_tags(skill_def.body_markdown)}"
                    )
            except (ValueError, IndexError, Exception) as e:
                logger.warning("技能指令注入失败", skill_ref=skill_ref, error=str(e))
        return fragments

