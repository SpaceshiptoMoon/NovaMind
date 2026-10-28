"""
Agent 对话服务

编排 Agent 对话的完整流程：会话管理 → 上下文构建（三层记忆） → ReAct 循环 → SSE 流式输出 → 结果持久化。
"""
import asyncio
import base64
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.core.ws import envelope
from novamind.engines.agent.agent_engine import AgentEngine, AgentEvent
from novamind.engines.agent.memory.context_scrubber import StreamingContextScrubber
from novamind.engines.agent.memory.interfaces import MemorySnapshot
from novamind.engines.agent.memory.memory_manager import MemoryManager
from novamind.engines.agent.prompt_builder import SystemPromptBuilder
from novamind.engines.agent.tool.base import ToolContext
from novamind.engines.search.ports import WebSearchPort
from novamind.features.agent.attachments.repository import ChatAttachmentRepository
from novamind.features.agent.exceptions import AgentError, AgentNotFoundError
from novamind.features.agent.models.agent import AgentDefinition
from novamind.features.agent.models.message import AgentMessage
from novamind.features.agent.models.session import AgentSession
from novamind.features.agent.repository.agent_repository import (
    MessageRepository,
    SessionRepository,
    ToolCallRepository,
)
from novamind.features.agent.repository.memory_search_repository import MemorySearchRepository
from novamind.features.agent.schemas.agent_schema import (
    ContextUsageResponse,
    SystemPromptResponse,
)
from novamind.features.agent.services.agent_service import AgentService
from novamind.features.agent.services.host_knowledge_search import (
    HostKnowledgeSearchPort,
)
from novamind.features.agent.services.host_memory_store import (
    HostMemorySearchPort,
    HostMemoryStorePort,
)
from novamind.features.agent.tool.builtins.plan_output import PlanOutputTool
from novamind.features.user.exceptions import ModelConfigNotFoundError
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.setting.yaml_config.loader import get_config
from novamind.shared.ai_models.base_model import LLMCapabilities, resolve_capabilities
from novamind.shared.prompts.prompt_manager import PromptManager
from novamind.shared.utils.time_utils import now_china
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


def _agent_memory_flag(key: str) -> bool:
    """读 agent.memory 配置节的布尔开关（缺节/缺键一律 False）。

    MemoryManager 记忆开关的宿主侧读取点——引擎（engines/agent）不 import
    setting，开关值在此读出后经构造链注入。
    """
    try:
        return bool(getattr(get_config().agent.memory, key, False))
    except Exception:
        return False

# Plan-and-Execute 步骤状态值（与 novamind.engines.agent.flow.planning_flow 常量对齐；
# 本地定义避免 features → engines 仅为此拉 import）
NOT_STARTED_VALUE = "not_started"
IN_PROGRESS_VALUE = "in_progress"


class AgentChatService:
    """Agent 对话服务"""

    _CACHE_TTL = 300  # 系统提示缓存 5 分钟

    # 类级共享缓存（prompt cache 前缀稳定性）：service 每请求新建，实例级缓存
    # 永远跨不了请求（形同虚设）。提到类级后同 agent+tools+model 的 system
    # prompt 在 TTL 窗口内字节恒定，frozen_memory 同理——记忆写入不会即时
    # 反映到当前会话（这正是"冻结"语义：新记忆下一个 TTL 窗口/会话才可见）。
    # 单进程 asyncio 下 dict 读写无 await 点即原子；多 worker 部署各自独立，
    # 前缀稳定性按 worker 内保证。上限防长生命周期进程无限增长。
    _PROMPT_CACHE: dict[str, tuple[str, float]] = {}
    _FROZEN_MEMORY_CACHE: dict[str, tuple[str, float]] = {}
    _CLASS_CACHE_MAX = 256

    def __init__(
        self,
        db: AsyncSession,
        agent_service: AgentService,
        model_config_service: ModelConfigService,
        agent_engine: AgentEngine,
        todo_store: Any | None = None,
        memory_search_repo: MemorySearchRepository | None = None,
        minio_client: Any | None = None,
        memory_store_port: HostMemoryStorePort | None = None,
        memory_search_port: HostMemorySearchPort | None = None,
        knowledge_search_port: HostKnowledgeSearchPort | None = None,
        attachment_read_port: Any | None = None,
        web_search_port: WebSearchPort | None = None,
        prompt_provider: PromptManager | None = None,
    ):
        """仅装配仓储与提示构建器；引擎端口由 build_agent_chat_service 注入，不在此内部构造。"""
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
        self._attachment_read_port = attachment_read_port
        self._web_search_port = web_search_port
        self._prompt_provider = prompt_provider
        self.msg_repo = MessageRepository(db)
        self.tc_repo = ToolCallRepository(db)
        self.session_repo = SessionRepository(db)
        self.attachment_repo = ChatAttachmentRepository(db)
        self._prompt_builder = SystemPromptBuilder(
            tool_registry=agent_engine.tool_executor.tool_registry,
        )

    async def chat_stream(
        self,
        user_id: int,
        agent_id: int,
        content: str,
        session_id: str | None = None,
        llm_model: str | None = None,
        enable_thinking: bool = False,
        deep_research: bool = False,
        stream: bool = True,
        attachment_ids: list[int] | None = None,
        approval_registry: Any | None = None,
        event_sink: Any | None = None,
        steering_queue: Any | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行 Agent 对话，返回事件流（dict 事件，经 WS 推送）。

        Args:
            user_id: 当前用户 ID。
            agent_id: Agent 主键 ID。
            content: 用户输入正文。
            session_id: 业务会话 ID；None 时新建会话。
            llm_model: 覆盖 Agent 配置的模型名；None 用 Agent 配置或用户默认。
            enable_thinking: 是否启用思考过程输出。
            deep_research: 是否开启深度研究模式（本轮提示增强，引导复杂课题优先调用 research 工具）。
            stream: 是否流式生成。
            attachment_ids: 随消息引用的附件 ID 列表。
            approval_registry: 异步审批注册表（WS 端点注入，DANGEROUS 工具需用户决策）。
            event_sink: 审批请求等旁路事件的接收器。
            steering_queue: 运行中插话队列（WS 端点注入；agent 执行期间用户插话
                在 ReAct 轮边界注入上下文，作为 user 消息落库）。

        Returns:
            事件字典异步生成器，涵盖 session/context_usage/compaction/content/reasoning/
            tool_call/tool_result/sources/done/error 等类型。

        Raises:
            AgentError: 未配置可用的 LLM 模型（经 error 事件 yield，不以异常冒泡）。
        """
        try:
            agent, conv, user_msg = await self._prepare(
                user_id, agent_id, content, session_id, llm_model, attachment_ids
            )
            # 消毒后 content 统一贯穿后续全部消费点（PlanningFlow user_query/
            # 会话标题等）：与 DB 落库形态一致，避免「上下文里消毒、step prompt
            # 里裸原文」的双版本不一致。
            content = user_msg.content or content

            # user 消息（和新建的会话行）在此提前提交：流式主循环可能含 research
            # 等长任务（单工具最长 15min），事务横跨全程会钉住连接并持有行锁
            # （阻塞并发改知识绑定等写操作）；此后工具/消息落库各自 flush，
            # 终态仍由 _handle_done 统一 commit。
            await self.db.commit()

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
            memory_manager = await self._create_memory_manager(
                agent, user_id, model, conv.id,
                memory_store, memory_search, prompt_provider,
            )

            llm_client, tools, messages, snapshot, _, caps = await self._build_context(
                agent, conv, user_id, model, content, memory_manager,
                deep_research=deep_research,
            )
            # 深度研究模式引导块已作为 overlay 在 build_context 内注入
            # （计量前，与记忆预取/附件清单同管线），此处不再单独 mutate 消息。
            # 调试向预览：会话级上下文用量（ContextMeter）+ 压缩事件（CompactionItem）
            # 在事件循环之前 emit，前端输入框仪表即时更新、压缩发生时插标记行
            yield self._emit("context_usage", {
                "used_tokens": snapshot.total_tokens,
                "context_window": snapshot.context_window,
                "system_tokens": snapshot.system_tokens,
                "tools_tokens": snapshot.tools_tokens,
                "messages_tokens": snapshot.messages_tokens,
                "reserved_tokens": snapshot.reserved_tokens,
                "compressed": snapshot.compressed,
                "compression_ratio": snapshot.compression_ratio,
            })
            if snapshot.compressed:
                yield self._emit("compaction", {
                    "conversation_id": conv.id,
                    "summarized_count": snapshot.compressed_count,
                    "summary": snapshot.compaction_summary,
                    "compression_ratio": snapshot.compression_ratio,
                    "tokens_after": snapshot.total_tokens,
                    "created_at": datetime.now(UTC).isoformat(),
                })

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
            # 本地工作区端口：会话绑定了工作区即注入（绑定本身即授权，
            # 不要求 agent 单独勾选——本地文件夹模式下工具默认必带）
            if (conv.extra_config or {}).get("workspace"):
                from novamind.features.agent.services.local_workspace.assembly import (
                    build_local_workspace_port,
                )

                context["local_workspace_port"] = await build_local_workspace_port(
                    self.db, user_id, conv
                )
            else:
                context["local_workspace_port"] = None
            # 知识检索管线配置（批2）：会话级知识绑定 + 会话模型 LLM。
            # llm_client 是 _build_context 已解析的会话模型客户端——改写/打分与主回答
            # 同模型，修掉 QA「改写固定用用户默认模型」的错位；会话无绑定时配置仍注入
            # （管线质量层默认生效），仅范围约束为不限定。
            session_bindings = (conv.extra_config or {}).get("knowledge_bindings")
            context["knowledge_pipeline"] = {
                "llm_client": llm_client,
                "knowledge_bindings": session_bindings,
                "conversation_history": [
                    {"role": m.get("role"), "content": str(m.get("content") or "")}
                    for m in messages[-6:]
                    if m.get("role") in ("user", "assistant")
                ],
            }
            context["attachment_read_port"] = self._attachment_read_port
            context["memory_store_port"] = memory_store
            context["memory_search_port"] = memory_search
            context["embedding_client_resolver"] = self._build_embedding_resolver(user_id)

            # E6 子 agent 委派：Agent 勾选 task 工具时注入 SubAgentRunner
            if "task" in (agent.enabled_tools or []):
                from novamind.engines.agent.subagent import SubAgentRunner

                context["subagent_runner"] = SubAgentRunner(
                    agent_engine=self.agent_engine,
                    tool_executor=self.agent_engine.tool_executor,
                    client_factory=self._subagent_client_factory(user_id),
                    model=model,
                    enabled_tools=agent.enabled_tools or [],
                    enabled_mcp_ids=await self._filter_visible_mcp_ids(
                        user_id, agent.enabled_mcp_servers or []
                    ),
                    parent_context=context,
                )
            else:
                context["subagent_runner"] = None

            # 深度研究（批3）：Agent 勾选 research 工具时注入请求级服务工厂。
            # 每次调用构造独立 DeepResearchService：db session 用全局工厂新开
            # （研究内部 rollback/错误恢复不得连坐外层 chat 事务）、web 适配器
            # 按请求 cleanup；space_id=None 时内部源按无空间处理（SearchService
            # 层拦截，内部检索跳过只走外部）。
            context["research_service_factory"] = (
                await self._build_research_service_factory()
                if "research" in (agent.enabled_tools or [])
                else None
            )

            # E5 异步审批：注入 approval_registry + event_sink（WS 端点传入，
            # ApprovalHook DANGEROUS 时发 approval_request + 等用户决策）
            context["approval_registry"] = approval_registry
            context["event_sink"] = event_sink

            full_response = ""
            full_reasoning = ""
            collected_sources: list[dict[str, Any]] = []
            scrubber = StreamingContextScrubber()
            reasoning_scrubber = StreamingContextScrubber()
            # 按迭代切分 AI 文本：full_response 仍作流级清洗累计（scrubber 行为不变），
            # 用 iteration_start 偏移把每轮 AI 文本分配给该轮决策消息，
            # 最终回答只取最后一轮（无工具调用）的文本，避免中间文本被吞进最终答案
            iteration_start = 0
            # 同理按轮切分 reasoning：每轮决策消息存该轮思考过程，最终回答存最后一轮，
            # 供前端每个 ReAct 步骤显示 think
            iteration_reasoning_start = 0

            # 上下文溢出时的自动压缩回调（tools 透传：前缀对齐压缩 + 预算扣减）
            async def _compress_on_overflow(msgs):
                """溢出兜底压缩回调：透传 tools（前缀对齐压缩重放 + 预算扣减）。"""
                return await self._compress_messages(
                    msgs, memory_manager, model, agent.context_window or 32768, conv.id,
                    tools=tools,
                )

            # E7 Plan-and-Execute：Agent extra_config.plan_mode 时用 PlanningFlow 编排。
            # plan 模式强依赖工具（plan_output/每步工具执行），模型无工具能力时
            # 静默降级=计划环节全空转，直接阻断并明示，不出错误结果。
            plan_mode = bool((agent.extra_config or {}).get("plan_mode"))
            if plan_mode and not caps.tools:
                await self._save_error_message(
                    conv,
                    "当前模型不支持工具调用，无法使用计划模式（Plan-and-Execute）。"
                    "请更换支持工具调用的模型，或在 Agent 设置中关闭计划模式。",
                    extra={"error": True, "plan_mode_blocked": True},
                )
                yield self._emit("error", {
                    "content": "当前模型不支持工具调用，无法使用计划模式（Plan-and-Execute）。"
                               "请更换支持工具调用的模型，或在 Agent 设置中关闭计划模式。",
                })
                return

            # 思考模式协商：模型不支持 thinking 时强制关（声明 False=实测不支持）
            effective_thinking = enable_thinking and caps.thinking
            if plan_mode:
                from novamind.engines.agent.flow import PlanningFlow

                event_gen = PlanningFlow(self.agent_engine).execute(
                    llm_client=llm_client,
                    messages=messages,
                    tools=tools,
                    context=context,
                    user_query=content,
                    max_tokens=agent.max_tokens,
                    temperature=agent.temperature,
                    top_p=agent.top_p,
                    enable_thinking=effective_thinking,
                    stream=stream,
                    compress_fn=_compress_on_overflow,
                    max_iterations=agent.max_tool_calls_per_turn or 5,
                )
            else:
                event_gen = self.agent_engine.run(
                    llm_client=llm_client,
                    messages=messages,
                    tools=tools,
                    context=context,
                    stream=stream,
                    enable_thinking=effective_thinking,
                    max_iterations=agent.max_tool_calls_per_turn,
                    max_tokens=agent.max_tokens,
                    temperature=agent.temperature,
                    top_p=agent.top_p,
                    compress_fn=_compress_on_overflow,
                    steering_queue=steering_queue,
                )
            async for event in event_gen:
                # 跟踪最新 ReAct 轮号：每条携带 iteration 的事件都更新 current_iteration，
                # 供本轮 assistant_tool_calls/tool_call/tool_result/done 落库时打 iteration 标签。
                # 注意最终回答属于最后一轮（无工具调用那轮），其 iteration 由该轮 content/reasoning
                # 事件推进，故不能只在 assistant_tool_calls 分支设置。
                if "iteration" in event.data:
                    raw_iter = event.data.get("iteration")
                    if plan_mode:
                        # plan 模式 iteration 全局连续化：内层引擎每步从 1 重计数，
                        # 加 plan 步偏移后写回 event.data——落库与前端收到的事件同源同值，
                        # 前端按 iteration 分组不再跨计划步碰撞。偏移仅在内层 done 时推进。
                        event.data["iteration"] = context.get("plan_iter_offset", 0) + (raw_iter or 0)
                    context["current_iteration"] = event.data.get("iteration")
                if event.event_type == "plan.created":
                    # 计划生成：落库 role='plan' 消息（extra.plan 存 title/steps），
                    # 并在 context 建立 plan_state 单一事实源——后续 plan.* 事件推进
                    # statuses，经 update_extra 持久化终态（历史回放可还原进度）
                    await self._handle_plan_created(event, conv, context)
                    yield self._emit("plan.created", event.data)
                elif event.event_type == "plan.step_started":
                    context["plan_step_index"] = event.data.get("step_index")
                    await self._apply_plan_step_status(context, event.data.get("step_index"), IN_PROGRESS_VALUE)
                    yield self._emit("plan.step_started", event.data)
                elif event.event_type == "plan.step_completed":
                    await self._apply_plan_step_status(context, event.data.get("step_index"), "completed")
                    yield self._emit("plan.step_completed", event.data)
                elif event.event_type == "plan.step_failed":
                    await self._apply_plan_step_status(context, event.data.get("step_index"), "blocked")
                    yield self._emit("plan.step_failed", event.data)
                elif event.event_type == "plan.completed":
                    # 外层 done 前置标志：plan 模式下区分内层/外层 done，外层才落最终 summary；
                    # 同时把 summary/interrupted 写入 plan_state 持久化（计划终态）
                    state = context.get("plan_state")
                    if state is not None:
                        state["summary"] = event.data.get("summary", "")
                        state["interrupted"] = bool(event.data.get("interrupted"))
                        await self._persist_plan_state(context)
                    context["plan_finalizing"] = True
                    yield self._emit("plan.completed", event.data)
                elif event.event_type.startswith("plan."):
                    yield self._emit(event.event_type, event.data)
                elif event.event_type == "steering":
                    # 运行中插话注入：作为 user 消息落库（与首条 user 同构），
                    # 历史回放可还原插话位置；引擎已把同文本注入内存上下文
                    await self.agent_service.save_message(
                        conversation_id=conv.id,
                        role="user",
                        content=event.data.get("content"),
                        extra={"steering": True, "iteration": event.data.get("iteration")},
                    )
                    yield self._emit("steering", event.data)
                elif event.event_type == "loop_warning":
                    # loop_detection 注入的纠偏警告：落库 role='notice'，轨迹可见
                    await self.agent_service.save_message(
                        conversation_id=conv.id,
                        role="notice",
                        content=event.data.get("content"),
                        extra={"notice": True, "iteration": event.data.get("iteration")},
                    )
                    yield self._emit("loop_warning", event.data)
                elif event.event_type == "assistant_tool_calls":
                    # AI 决定调用工具：落库一条 role=assistant 决策消息，content 存该轮 AI 真实输出文本
                    # （从 full_response 当前偏移截取，经流级 scrubber 清洗），extra.tool_calls 存该轮全部工具。
                    # reasoning 同轮切片存决策消息 reasoning 字段，供前端每步显示 think。
                    # 还原完整 ReAct 链路：user → assistant(决策文本) → tool → ... → assistant(最终)。
                    iteration_text = full_response[iteration_start:]
                    iteration_reasoning = full_reasoning[iteration_reasoning_start:]
                    await self._handle_assistant_tool_calls(
                        event, conv, context, iteration_text, iteration_reasoning
                    )
                    iteration_start = len(full_response)
                    iteration_reasoning_start = len(full_reasoning)
                    yield self._emit("assistant_tool_calls", event.data)
                elif event.event_type == "tool_call":
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
                    # plan 模式内层 ReAct 的 done：先 flush 再切片落库该步结论文本
                    # （role='assistant' + extra.plan_step_index），推进迭代偏移并按步
                    # 重置累积器；只有 plan.completed 之后的 done（plan_finalizing）才落最终 summary
                    if plan_mode and not context.get("plan_finalizing"):
                        remaining = scrubber.flush()
                        if remaining:
                            full_response += remaining
                        remaining_r = reasoning_scrubber.flush()
                        if remaining_r:
                            full_reasoning += remaining_r
                        step_text = full_response[iteration_start:]
                        step_reasoning = full_reasoning[iteration_reasoning_start:] or None
                        if event.data.get("truncated", False):
                            step_text += "\n\n[本步因达到迭代上限被截断]"
                        await self._handle_plan_step_result(conv, context, step_text, step_reasoning)
                        # 迭代偏移推进 + 累积器按步重置（防跨步串文本 + 内存有界）
                        context["plan_iter_offset"] = context.get("current_iteration", 0)
                        full_response = ""
                        full_reasoning = ""
                        iteration_start = 0
                        iteration_reasoning_start = 0
                        continue
                    # flush scrubber buffer
                    remaining = scrubber.flush()
                    if remaining:
                        full_response += remaining
                    remaining_r = reasoning_scrubber.flush()
                    if remaining_r:
                        full_reasoning += remaining_r
                    if event.data.get("truncated", False):
                        full_response += "\n\n[Agent 已达到最大迭代次数，对话被截断]"
                    if plan_mode and context.get("plan_finalizing"):
                        # 外层 done：最终回答用 PlanningFlow _finalize 的 summary，
                        # 而非累积切片（各步 ReAct 文本已由 assistant_tool_calls 落决策消息）
                        final_text = event.data.get("full_response", "")
                        final_reasoning = None
                    else:
                        # 最终回答 = 最后一轮（无工具调用）的 AI 文本（从 iteration_start 截取），
                        # 含 flush 尾部与截断标记；前序各轮文本已归入各自决策消息
                        final_text = full_response[iteration_start:]
                        # 最终 reasoning = 最后一轮思考（前序各轮已归入各自决策消息）
                        final_reasoning = full_reasoning[iteration_reasoning_start:] or None
                    # 发送结构化来源引用（对齐 QA sources 事件）
                    if collected_sources:
                        yield self._emit("sources", {"sources": collected_sources})
                    done_data = await self._handle_done(
                        event, conv, content, final_text,
                        reasoning=final_reasoning,
                        sources=collected_sources or None,
                        iteration=context.get("current_iteration"),
                    )
                    # E1 可观测性：done 加 cost_usd + 写 agent_usage 表
                    done_data = await self._record_usage(
                        done_data, user_id, conv, agent_id, model
                    )
                    yield self._emit("done", done_data)

                elif event.event_type == "error":
                    # 落库错误消息（role='assistant' + extra.error），供历史回放还原失败对话
                    await self._save_error_message(
                        conv, event.data.get("content", ""), extra={"error": True}
                    )
                    yield self._emit("error", event.data)

                elif event.event_type == "context_overflow":
                    logger.warning("上下文溢出，建议压缩", conversation_id=conv.id)
                    overflow_msg = "对话上下文过长，请开启新会话或缩短对话历史"
                    await self._save_error_message(
                        conv, overflow_msg, extra={"error": True, "overflow": True}
                    )
                    yield self._emit("error", {"content": overflow_msg})

        except AgentNotFoundError:
            yield self._emit("error", {"content": "Agent 不存在"})
        except (asyncio.CancelledError, GeneratorExit):
            # 客户端断连（WS close）→ run_stream_to_ws aclose 触发；回滚未提交事务，
            # assistant 消息不落库（user 消息已在 _prepare 后提前 commit，见上）
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

        reconciler = None
        if get_config().agent.memory.backend == "mem0":
            try:
                reconciler = await AgentChatService._build_memory_reconciler(
                    model_config_service=self.model_config_service,
                    user_id=user_id,
                    agent_id=agent.id,
                    memory_store=memory_store,
                    memory_search=memory_search,
                    embedding_factory=embedding_factory if memory_search else None,
                )
            except Exception as e:
                # 装配失败（模型参数缺失/mem0ai 未装）→ warning 后走 builtin，
                # 不阻断对话
                logger.warning("Mem0 reconciler 装配失败，降级 builtin", error=str(e))

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
            reconciler=reconciler,
            memory_compaction_async=_agent_memory_flag("compaction_async"),
            memory_on_turn_done=_agent_memory_flag("on_turn_done"),
        )

    @staticmethod
    def _subagent_client_factory(self, user_id: int):
        """构造子 agent 客户端工厂（业务侧闭包用户身份与 LLM→VLM 兜底策略）。

        引擎（SubAgentRunner）只收 ``async factory(model) -> 客户端``；
        凭证解析与降级策略属业务，不进引擎接口。
        """
        mcs = self.model_config_service

        async def factory(model: str):
            try:
                return await mcs.get_llm_client_by_model(user_id, model)
            except Exception:
                return await mcs.get_vlm_client_by_model(user_id, model)

        return factory

    async def _build_memory_reconciler(
        model_config_service: ModelConfigService,
        user_id: int,
        agent_id: int,
        memory_store: HostMemoryStorePort,
        memory_search: HostMemorySearchPort | None,
        embedding_factory=None,
    ):
        """构造 Mem0 调和器：按用户当前默认 LLM/embedding 模型的原始连接参数现配。

        每次请求新配一份（模型配置变更即时生效）；AsyncMemory 实例在 reconciler
        内部按参数指纹 LRU，避免同用户反复握手。

        Args:
            model_config_service: 模型配置服务（绑定任务/请求各自的新 session）。
            user_id: 用户 ID（决定 LLM/embedding 连接参数）。
            agent_id: Agent ID（Mem0 agent_id 命名空间）。
            memory_store: MySQL 真源读写端口。
            memory_search: ES hybrid 端口，可空。
            embedding_factory: embedding 客户端工厂（Mem0 产出索引 ES 用），可空。

        Returns:
            Mem0Reconciler 实例。

        Raises:
            Exception: mem0ai 缺失在首次 reconcile 才暴露；模型配置缺失此处即抛。
        """
        llm_params = await model_config_service.get_model_connection_params(
            user_id, "llm"
        )
        embedding_params = await model_config_service.get_model_connection_params(
            user_id, "embedding"
        )
        # Mem0 只有 openai 兼容 provider；anthropic 等其他协议端点用 OpenAI SDK
        # 调用会得到包着错误的 200（choices=null）→ 管线全空转。装配期显式拒绝，
        # 由调用方降级 builtin，不偷换成别的模型
        for name, params in (("llm", llm_params), ("embedding", embedding_params)):
            if params.get("protocol") != "openai":
                raise ModelConfigNotFoundError(
                    message=(
                        f"Mem0 调和需要 openai 兼容协议，当前 {name} 模型 "
                        f"{params.get('model')} 协议为 {params.get('protocol')}"
                    )
                )
        # Mem0 是同步构造/异步调用混合 API，连接参数在构造期解析（当前请求的
        # 事件循环内完成解密），不跨事件循环传递 coroutine
        es_cfg = get_config().elasticsearch
        mem_cfg = get_config().agent.memory
        # mem0 ES provider 拼 host:port，host 必须不带端口
        from novamind.engines.agent.memory.mem0_reconciler import Mem0Reconciler, split_es_host

        es_host, es_port = split_es_host(es_cfg.hosts[0] if es_cfg.hosts else "http://localhost")

        return Mem0Reconciler(
            llm_params={
                "model": llm_params["model"],
                "openai_base_url": llm_params["base_url"],
                "api_key": llm_params["api_key"],
            },
            embedding_params={
                "model": embedding_params["model"],
                "openai_base_url": embedding_params["base_url"],
                "api_key": embedding_params["api_key"],
            },
            es_params={
                "host": es_host,
                "port": es_port,
                "user": es_cfg.username,
                "password": es_cfg.password,
                # Mem0 embedder 用用户配置的 embedding 模型，维度以配置声明为准
                "embedding_model_dims": es_cfg.default_embedding_dim,
            },
            store=memory_store,
            search=memory_search,
            embedding_factory=embedding_factory,
            es_collection=mem_cfg.es_collection,
            history_size=mem_cfg.history_size,
            lru_size=mem_cfg.lru_size,
            owner_user_id=user_id,
            owner_agent_id=agent_id,
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

    async def _build_research_service_factory(self):
        """构造 DeepResearchService 工厂（供 research 工具经 context 调用）。

        每次调用构造独立服务实例：db session 用全局工厂新开（研究内部 rollback /
        错误恢复不得连坐外层 chat 事务）、web 适配器按请求构造、cleanup 统一关闭；
        ES 客户端经 shared/storage 客户端工厂取单例（与 web 适配层 dependencies 同款装配）。
        """
        from novamind.core.database.database import get_session_factory
        from novamind.shared.storage.client_factory import get_elasticsearch_client

        es_client = await get_elasticsearch_client()

        def factory():
            from novamind.features.deep_research.services.deep_research_service import (
                DeepResearchService,
            )

            return DeepResearchService(
                get_session_factory()(),
                model_config_service=self.model_config_service,
                es_client=es_client,
            )

        return factory

    # ==================== 阶段方法 ====================

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

    async def _filter_visible_mcp_ids(self, user_id: int, raw_ids: list[int]) -> list[int]:
        """过滤掉当前用户不可见（他人私有）的 MCP 服务器 id。

        聊天路径的失败方向安全：历史数据可能含越权 id（归属校验前落库），
        此处静默剔除并告警而非抛错——能力缺失优于杀死进行中的会话。

        Args:
            user_id: 当前用户 ID。
            raw_ids: agent 配置的 MCP 服务器 id 列表。

        Returns:
            仅含可见（自有或系统级）服务器 id 的列表。
        """
        if not raw_ids:
            return []
        from novamind.features.agent.repository.agent_repository import McpServerRepository

        visible = {s.id for s in await McpServerRepository(self.db).list_by_user(user_id)}
        filtered = [i for i in raw_ids if i in visible]
        dropped = [i for i in raw_ids if i not in visible]
        if dropped:
            logger.warning(
                "agent 启用了不可见的 MCP 服务器，已在本次会话中剔除",
                user_id=user_id, dropped_mcp_ids=dropped,
            )
        return filtered

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
        enabled_mcp_ids = await self._filter_visible_mcp_ids(
            user_id, agent.enabled_mcp_servers or []
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

    # ==================== 系统提示辅助 ====================

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

    def _get_cached_prompt(self, cache_key: str) -> str | None:
        """查询系统提示缓存（类级——service 每请求新建，实例级缓存永远跨不了请求）"""
        return self._get_class_cached(self._PROMPT_CACHE, cache_key)

    def _set_cached_prompt(self, cache_key: str, prompt: str):
        """写入系统提示缓存"""
        self._set_class_cached(self._PROMPT_CACHE, cache_key, prompt)

    # ==================== 记忆注入 ====================

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

    # ==================== 深度研究模式（批3） ====================
    # 请求级提示增强：用户在输入框开启「深度研究」chip 时，本轮消息 prepend 引导块。
    # research 工具本身始终对模型可见（agent.enabled_tools 门控），开关只影响选择
    # 优先级；提示块不落库（messages 是构建态副本），单轮生效。

    RESEARCH_MODE_HINT = (
        "<system-research-mode>\n"
        "[系统提示：用户已开启深度研究模式。本轮若课题需要多源调研、横向对比或全面分析，"
        "优先调用 research 工具发起深度研究（耗时数分钟，调用前先用一句话告知用户），"
        "再基于研究报告作答；简单问答不需要研究，直接回答。]\n"
        "</system-research-mode>"
    )

    # ==================== 附件清单注入（对齐 deer-flow） ====================
    # 设计：附件正文不注入任何消息 content（DB 消息 content 始终保持干净原文）。
    # 每轮只把 <uploaded_files> 清单 prepend 到最后一条用户消息，模型经
    # read_attachment 工具按 attachment_id + offset/limit 按需读取正文。
    # 收益：多轮不累积正文 token；compaction 丢的只是历史文本，清单每轮重建、
    # 文件永远可重读；不再有按位置索引对齐的错位问题。

    MANIFEST_MAX_FILES_PER_SECTION = 10
    MANIFEST_PREVIEW_CHARS = 500
    IMAGE_TYPES = {"jpg", "jpeg", "png", "gif", "webp"}

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

    async def _is_vlm_model(self, model_name: str, user_id: int) -> bool:
        """判断模型是否为 VLM 视觉模型"""
        try:
            vlm_models = await self.model_config_service.list_available_models(
                user_id, "vlm"
            )
            return model_name in vlm_models
        except Exception:
            return False

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

    # ==================== 技能指令注入 ====================

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

    # ==================== 来源提取 ====================

    def _extract_sources(
        self, event: AgentEvent, collected_sources: list[dict[str, Any]]
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

    async def _handle_plan_created(
        self, event: AgentEvent, conv: AgentSession, context: dict[str, Any]
    ) -> None:
        """处理 plan.created 事件：落库 role='plan' 消息（extra.plan 存计划清单），
        并在 context 建立 plan_state 单一事实源（statuses 全 not_started）与 plan_msg_id，
        供后续 plan.* 事件推进状态后经 _persist_plan_state 持久化终态。
        """
        plan = event.data
        steps = plan.get("steps", [])
        msg = await self.agent_service.save_message(
            conversation_id=conv.id,
            role="plan",
            content=plan.get("title") or None,
            extra={"plan": {
                "title": plan.get("title", ""),
                "steps": steps,
                "step_count": plan.get("step_count", len(steps)),
                "statuses": [NOT_STARTED_VALUE] * len(steps),
            }},
        )
        context["plan_msg_id"] = msg.id
        context["plan_state"] = {
            "title": plan.get("title", ""),
            "steps": steps,
            "step_count": plan.get("step_count", len(steps)),
            "statuses": [NOT_STARTED_VALUE] * len(steps),
        }

    async def _apply_plan_step_status(
        self, context: dict[str, Any], step_index: Any, status: str
    ) -> None:
        """推进 plan_state 中指定步骤的状态并持久化（step_started/completed/failed 共用）。

        Args:
            context: 执行上下文（含 plan_state/plan_msg_id）。
            step_index: 步骤下标；None 或越界时静默跳过（防御畸形事件）。
            status: 目标状态（in_progress/completed/blocked）。
        """
        state = context.get("plan_state")
        if state is None or not isinstance(step_index, int):
            return
        statuses = state.get("statuses")
        if not isinstance(statuses, list) or step_index < 0 or step_index >= len(statuses):
            return
        statuses[step_index] = status
        await self._persist_plan_state(context)

    async def _persist_plan_state(self, context: dict[str, Any]) -> None:
        """把 context['plan_state'] 整体写回 plan 消息 extra（statuses/summary 终态）。

        update_extra 是整体替换：调用方必须传完整 plan dict。失败不阻断对话（warning）。
        """
        plan_msg_id = context.get("plan_msg_id")
        state = context.get("plan_state")
        if not plan_msg_id or not state:
            return
        try:
            await self.msg_repo.update_extra(plan_msg_id, {"plan": dict(state)})
        except Exception as e:
            logger.warning("计划状态持久化失败", error=str(e))

    async def _handle_plan_step_result(
        self,
        conv: AgentSession,
        context: dict[str, Any],
        step_text: str,
        step_reasoning: str | None,
    ) -> None:
        """落库单步结论文本：role='assistant' + extra.plan_step_index 标记归属。

        内层 ReAct 最后一轮（不调工具、给出该步结论）不走决策消息落库路径，
        此处接通持久化（原三断路之一）。步内无产出时跳过；失败不阻断（warning）。
        """
        if not step_text and not step_reasoning:
            return
        try:
            await self.agent_service.save_message(
                conversation_id=conv.id,
                role="assistant",
                content=step_text or None,
                reasoning=step_reasoning,
                extra={"plan_step_index": context.get("plan_step_index")},
                iteration=context.get("current_iteration"),
            )
        except Exception as e:
            logger.warning("计划步骤结论落库失败", conversation_id=conv.id, error=str(e))

    async def _save_error_message(
        self, conv: AgentSession, content: str, extra: dict[str, Any] | None = None
    ) -> None:
        """落库错误/溢出消息（role='assistant' + extra.error），供历史回放还原失败对话。
        失败不阻断主流程（仅 warning 日志）。
        """
        try:
            text = content if content.startswith("[错误]") else f"[错误] {content}"
            await self.agent_service.save_message(
                conversation_id=conv.id,
                role="assistant",
                content=text,
                extra=extra,
            )
        except Exception as e:
            logger.warning("错误消息落库失败", conversation_id=conv.id, error=str(e))

    async def _handle_assistant_tool_calls(
        self,
        event: AgentEvent,
        conv: AgentSession,
        context: dict[str, Any],
        iteration_text: str = "",
        iteration_reasoning: str = "",
    ) -> None:
        """处理 assistant_tool_calls 事件：落库「AI 决定调用工具」的 assistant 决策消息，
        并把 message_id 记入 context，供本轮 tool_call 记录关联（而非挂在 user 消息上）。

        content 存该轮 AI 真实输出文本（经流级 scrubber 清洗，可能为空），
        reasoning 存该轮思考过程（同轮切片，供前端每步显示 think），
        extra.tool_calls 存该轮全部 OpenAI 格式 tool_calls，
        供历史回放还原完整 ReAct 链路：user → assistant(决策文本) → tool → assistant(最终)。
        """
        tool_calls = event.data.get("tool_calls", [])
        extra: dict[str, Any] = {"tool_calls": tool_calls}
        # per-iteration usage + LLM 调用耗时（轨迹视图 per-message token/耗时展示）
        if event.data.get("usage"):
            extra["usage"] = event.data["usage"]
        if event.data.get("duration_ms") is not None:
            extra["duration_ms"] = event.data["duration_ms"]
        msg = await self.agent_service.save_message(
            conversation_id=conv.id,
            role="assistant",
            content=iteration_text or None,
            reasoning=iteration_reasoning or None,
            extra=extra,
            iteration=context.get("current_iteration"),
        )
        context["assistant_msg_id"] = msg.id

    async def _handle_tool_call(
        self,
        event: AgentEvent,
        user_msg: AgentMessage,
        conv: AgentSession,
        context: dict[str, Any],
    ) -> None:
        """处理 tool_call 事件：保存工具调用记录"""
        call_id = event.data.get("call_id", "")
        # 优先关联到本轮 assistant 决策消息（_handle_assistant_tool_calls 写入）；
        # 缺失时 fallback 到 user 消息，保持旧链路兼容
        assistant_msg_id = context.get("assistant_msg_id")
        tc = await self.tc_repo.create(
            message_id=assistant_msg_id if assistant_msg_id is not None else user_msg.id,
            conversation_id=conv.id,
            call_id=call_id or None,
            tool_name=event.data["tool_name"],
            tool_source="mcp" if event.data["tool_name"].startswith("mcp__") else "skill" if event.data["tool_name"].startswith("skill__") else "builtin",
            arguments=event.data.get("arguments", {}),
            status="running",
            iteration=context.get("current_iteration"),
        )
        context[f"tc_{call_id}"] = tc.id

    async def _handle_tool_result(
        self,
        event: AgentEvent,
        conv: AgentSession,
        context: dict[str, Any],
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
            iteration=context.get("current_iteration"),
        )

    async def _handle_done(
        self,
        event: AgentEvent,
        conv: AgentSession,
        user_content: str,
        full_response: str,
        reasoning: str | None = None,
        sources: list[dict[str, Any]] | None = None,
        iteration: int | None = None,
    ) -> dict[str, Any]:
        """处理 done 事件：保存 assistant 消息、更新统计、设置标题"""
        total_tokens = event.data.get("total_tokens", 0)

        # 最后一轮 per-iteration usage + LLM 调用耗时（轨迹视图 per-message token/耗时）
        done_extra: dict[str, Any] = {}
        if event.data.get("last_iteration_usage"):
            done_extra["usage"] = event.data["last_iteration_usage"]
        if event.data.get("last_iteration_duration_ms") is not None:
            done_extra["duration_ms"] = event.data["last_iteration_duration_ms"]

        assistant_msg = await self.agent_service.save_message(
            conversation_id=conv.id,
            role="assistant",
            content=full_response,
            token_count=total_tokens,
            reasoning=reasoning,
            extra=done_extra or None,
            iteration=iteration,
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
        done_data: dict[str, Any],
        user_id: int,
        conv: AgentSession,
        agent_id: int,
        model: str,
    ) -> dict[str, Any]:
        """E1 可观测性：done_data 加 cost_usd + 写 agent_usage 表。

        失败不阻断对话（仅 warning 日志）。
        """
        usage_breakdown = done_data.get("usage_breakdown") or {}
        if not usage_breakdown:
            return done_data
        try:
            from novamind.features.agent.repository.agent_usage_repository import (
                AgentUsageRepository,
            )
            from novamind.shared.ai_models.usage import CanonicalUsage, estimate_cost

            usage = CanonicalUsage(
                input_tokens=usage_breakdown.get("input_tokens", 0),
                output_tokens=usage_breakdown.get("output_tokens", 0),
                cache_read_tokens=usage_breakdown.get("cache_read_tokens", 0),
                cache_write_tokens=usage_breakdown.get("cache_write_tokens", 0),
                reasoning_tokens=usage_breakdown.get("reasoning_tokens", 0),
            )
            cost = estimate_cost(usage, model)
            done_data["cost_usd"] = float(cost)

            usage_repo = AgentUsageRepository()
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
        messages: list[dict],
        memory_manager: MemoryManager,
        model: str,
        context_window: int,
        conversation_id: int,
        tools: list[dict] | None = None,
    ) -> list[dict]:
        """将 OpenAI 格式消息压缩后返回（上下文溢出时调用）

        system prompt 不参与压缩：compressor 会把 turns_to_compress（可能含 index 0）
        序列化进摘要并从消息列表消失，溢出兜底后本轮将失去身份/安全约束。
        先摘出 system，压缩其余，最终按 [system, 摘要, tail...] 重排。

        tools 透传给前缀缓存对齐压缩（重放请求头使命中 KV cache），并计入
        压缩预算扣减——溢出重试的下一请求仍带同一 tools schema，不扣会二次溢出。
        """
        from novamind.engines.agent.memory.interfaces import MemoryMessage
        from novamind.engines.agent.memory.token_budget import TokenBudget

        # 摘出全部 system 消息（OpenAI 消息列表 system 只在头部，但按 role 过滤更稳）
        system_dicts = [m for m in messages if m.get("role") == "system"]
        rest = [m for m in messages if m.get("role") != "system"]
        if not rest:
            return messages

        # OpenAI dicts → MemoryMessage（仅非 system 部分）
        mem_msgs = []
        for m in rest:
            mem_msgs.append(MemoryMessage(
                role=m.get("role", "user"),
                content=m.get("content") or "",
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
                tool_name=m.get("name"),
            ))

        budget = TokenBudget(model)
        # 口径说明：此处 available = window - 4096 与 build_context 的 window - reserve(1024)
        # 是两套语义而非不一致——溢出兜底发生在流式生成中途，必须为"剩余生成量"留足空间
        # （该次请求可能还要输出长回复），故预留更大；build_context 的 reserve 仅是常规安全边际。
        available = context_window - 4096  # 留出生成空间
        if tools:
            available -= budget.count_text_tokens(json.dumps(tools, ensure_ascii=False))
        if available < 2000:
            return messages

        system_prompt = "\n\n".join(
            (d.get("content") or "") for d in system_dicts
        ) or None
        compressed, _, _ = await memory_manager._short_term._compression.compress(
            mem_msgs, available, budget, conversation_id=conversation_id,
            system_prompt=system_prompt, tools=tools or None,
        )

        # MemoryMessage → OpenAI dicts（system 前置，摘要 role 由 compressor 从
        # assistant/user 中选，不会产生双 system 冲突）
        result = [
            {"role": "system", "content": m.get("content") or ""}
            for m in system_dicts
        ]
        for mm in compressed:
            d: dict[str, Any] = {"role": mm.role}
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
