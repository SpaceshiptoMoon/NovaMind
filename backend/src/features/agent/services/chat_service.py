"""
Agent 对话服务

编排 Agent 对话的完整流程：会话管理 → 上下文构建（三层记忆） → ReAct 循环 → SSE 流式输出 → 结果持久化。

2026-11-15 拆分：事件落库族/上下文组装族/追问建议按 mixin 纯搬移至
chat_event_handlers.py / chat_context_builder.py / followup_suggestions.py，
方法经 MRO 挂到本类（调用方零改动）；本文件保留主循环与 detach 恢复面。
"""
import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.core.ws import envelope
from novamind.engines.agent.agent_engine import AgentEngine
from novamind.engines.agent.memory.context_scrubber import StreamingContextScrubber
from novamind.engines.agent.memory.memory_manager import MemoryManager
from novamind.engines.agent.prompt_builder import SystemPromptBuilder
from novamind.engines.search.ports import WebSearchPort
from novamind.features.agent.attachments.repository import ChatAttachmentRepository
from novamind.features.agent.exceptions import (
    AgentNotFoundError,
)
from novamind.features.agent.repository.agent_repository import (
    MessageRepository,
    SessionRepository,
    ToolCallRepository,
)
from novamind.features.agent.repository.memory_search_repository import MemorySearchRepository
from novamind.features.agent.services.agent_service import AgentService
from novamind.features.agent.services.chat_context_builder import ChatContextBuilderMixin
from novamind.features.agent.services.chat_event_handlers import (
    IN_PROGRESS_VALUE,
    ChatEventHandlersMixin,
)
from novamind.features.agent.services.context_assembly import (
    ChatPorts,
    build_tool_context,
)
from novamind.features.agent.services.followup_suggestions import FollowupSuggestionsMixin
from novamind.features.agent.services.host_knowledge_search import (
    HostKnowledgeSearchPort,
)
from novamind.features.agent.services.host_memory_store import (
    HostMemorySearchPort,
    HostMemoryStorePort,
)
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.prompts.prompt_manager import PromptManager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

logger = get_logger(__name__)

# TurnPersistence 自独立模块导入（本模块命名空间保留 re-export：
# group_orchestrator 等既有消费方 import 路径不变）
from novamind.features.agent.services.turn_persistence import TurnPersistence  # noqa: E402


class AgentChatService(
    ChatContextBuilderMixin, ChatEventHandlersMixin, FollowupSuggestionsMixin
):
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

            # 新轮次开始即清上一轮 detach 残留标记（running_turn/pending_approval）：
            # 进程崩溃后台 task 丢失时留下的僵尸标记在此自愈（同会话新轮次取代旧轮次）
            extra = dict(conv.extra_config or {})
            if "running_turn" in extra or "pending_approval" in extra:
                extra.pop("running_turn", None)
                extra.pop("pending_approval", None)
                conv.extra_config = extra
                flag_modified(conv, "extra_config")
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

            # 创建 MemoryManager（每请求实例）
            memory_manager = await self._create_memory_manager(
                agent, user_id, model, conv.id,
                memory_store, memory_search, prompt_provider,
            )

            llm_client, tools, messages, snapshot, _, caps, enabled_mcp_ids = (
                await self._build_context(
                    agent, conv, user_id, model, content, memory_manager,
                    deep_research=deep_research,
                )
            )
            # 按需工具目录机制：登记本轮 tools 列表引用（load_tools 激活时
            # 原地追加）与 MCP 授权边界；turn 结束（含异常路径）由 finally 清理
            self.agent_engine.tool_executor.begin_turn(
                tools, enabled_mcp_server_ids=enabled_mcp_ids
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

            # 工具执行上下文：单点装配（context_assembly，单聊/群聊共用）。
            # 端口条件注入（web_search 按勾选、local_workspace 按会话绑定、
            # subagent/research 按勾选）、知识管线配置、embedding resolver
            # 与 memory 上限全部收敛在装配函数内；服务层落库状态走 turn
            # （TurnPersistence），不再混入 context。
            turn = TurnPersistence()
            context = await build_tool_context(
                self.db,
                user_id=user_id,
                agent=agent,
                session=conv,
                conversation_id=conv.id,
                session_id=conv.session_id,
                model=model,
                llm_client=llm_client,
                conversation_history=[
                    {"role": m.get("role"), "content": str(m.get("content") or "")}
                    for m in messages[-6:]
                    if m.get("role") in ("user", "assistant")
                ],
                ports=ChatPorts(
                    web_search_port=self._web_search_port,
                    knowledge_search_port=self._knowledge_search_port,
                    memory_store_port=self._memory_store_port,
                    memory_search_port=self._memory_search_port,
                    attachment_read_port=self._attachment_read_port,
                ),
                model_config_service=self.model_config_service,
                agent_engine=self.agent_engine,
                approval_registry=approval_registry,
                event_sink=event_sink,
            )

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
                        event.data["iteration"] = turn.plan_iter_offset + (raw_iter or 0)
                    turn.iteration = event.data.get("iteration")
                if event.event_type == "plan.created":
                    # 计划生成：落库 role='plan' 消息（extra.plan 存 title/steps），
                    # 并在 turn 建立 plan_state 单一事实源——后续 plan.* 事件推进
                    # statuses，经 update_extra 持久化终态（历史回放可还原进度）
                    await self._handle_plan_created(event, conv, turn)
                    yield self._emit("plan.created", event.data)
                elif event.event_type == "plan.step_started":
                    turn.plan_step_index = event.data.get("step_index")
                    await self._apply_plan_step_status(turn, event.data.get("step_index"), IN_PROGRESS_VALUE)
                    yield self._emit("plan.step_started", event.data)
                elif event.event_type == "plan.step_completed":
                    await self._apply_plan_step_status(turn, event.data.get("step_index"), "completed")
                    yield self._emit("plan.step_completed", event.data)
                elif event.event_type == "plan.step_failed":
                    await self._apply_plan_step_status(turn, event.data.get("step_index"), "blocked")
                    yield self._emit("plan.step_failed", event.data)
                elif event.event_type == "plan.completed":
                    # 外层 done 前置标志：plan 模式下区分内层/外层 done，外层才落最终 summary；
                    # 同时把 summary/interrupted 写入 plan_state 持久化（计划终态）
                    state = turn.plan_state
                    if state is not None:
                        state["summary"] = event.data.get("summary", "")
                        state["interrupted"] = bool(event.data.get("interrupted"))
                        await self._persist_plan_state(turn)
                    turn.plan_finalizing = True
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
                        event, conv, turn, iteration_text, iteration_reasoning
                    )
                    iteration_start = len(full_response)
                    iteration_reasoning_start = len(full_reasoning)
                    yield self._emit("assistant_tool_calls", event.data)
                elif event.event_type == "tool_call":
                    await self._handle_tool_call(event, user_msg, conv, turn)
                    yield self._emit("tool_call", event.data)

                elif event.event_type == "tool_result":
                    await self._handle_tool_result(event, conv, turn)
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
                    if plan_mode and not turn.plan_finalizing:
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
                        await self._handle_plan_step_result(conv, turn, step_text, step_reasoning)
                        # 迭代偏移推进 + 累积器按步重置（防跨步串文本 + 内存有界）
                        turn.plan_iter_offset = turn.iteration or 0
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
                    if plan_mode and turn.plan_finalizing:
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
                        iteration=turn.iteration,
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
            # 显式 stop（前端 action=stop 后 close）→ consume task cancel → aclose 走到此；
            # 异常断连已不再走这条链（routes 层转后台续跑）。回滚未提交事务，
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
        finally:
            # 按需工具目录：清理本轮 tools 列表引用与已加载记录（含取消/异常
            # 路径），防引用悬挂污染下一轮
            self.agent_engine.tool_executor.end_turn()

    # ==================== 断连后台续跑（turn 状态标记） ====================

    async def mark_turn_running(self, session_id: str) -> None:
        """标记会话存在后台续跑中的轮次（断连 detach 时由 WS 端点调用）。

        前端重连经 GET /sessions/{id}/turn-state 查询此标记展示「后台运行中」。
        """
        await self._mutate_session_extra(session_id, lambda e: e.update({"running_turn": True}))

    async def save_pending_approval(self, session_id: str, data: dict) -> None:
        """持久化待审批请求（detach 后审批卡的重连恢复数据源）。"""
        await self._mutate_session_extra(session_id, lambda e: e.update({"pending_approval": data}))

    async def _mutate_session_extra(self, session_id: str, mutate) -> None:
        """读-改-写会话 extra_config（detach 标记的统一写入通道）；会话不存在静默跳过。"""
        try:
            conv = await self.session_repo.get_by_session_id(session_id)
            if conv is None:
                return
            extra = dict(conv.extra_config or {})
            mutate(extra)
            conv.extra_config = extra
            flag_modified(conv, "extra_config")
            await self.db.commit()
        except Exception as e:
            # 标记写失败不影响对话主链路（终态清理与下轮自愈兜底）
            logger.warning("会话 extra_config 标记写入失败", session_id=session_id, error=str(e))

    # ==================== 模型 & MemoryManager ====================


    # ==================== 追问建议 ====================

    # 追问生成的尾部对话窗口与输出条数（DeerFlow suggestions 同构：最近轮次 → 3 条）
    FOLLOWUP_CONTEXT_MESSAGES = 6
    FOLLOWUP_MAX_ITEMS = 3
    # 单条消息进 prompt 的截断长度（长回答只保留头部足够定位语义的部分）
    FOLLOWUP_MESSAGE_CHARS = 500




    def fork_for_session(self, session: AsyncSession) -> "AgentChatService":
        """派生绑定新 db 会话的分身（群聊成员并行 turn 专用）。

        AsyncSession 不可并发共享：分身的仓储/端口/模型配置服务全部重建并
        绑定到给定 session——方法是真方法（绑定分身自身），不再沿用主实例的
        属性（历史上 setattr 搬运绑定方法导致分身方法实际跑在主 session 上，
        与「逐一新建重绑」的设计意图相悖，此处一并修正）；无 db 状态的协作方
        （引擎/prompt 注册表/prompt 构建器/web 搜索端口/ES 记忆仓储）直接共享。

        走 ``__new__`` + 显式字段赋值而非 ``__init__``：__init__ 会重建
        _prompt_builder（深访 agent_engine.tool_executor），而 prompt 构建
        器无 db 状态、分身应与主实例共享同一注册表视图。新增 __init__ 字段
        时在此同步补一行——字段清单就在本类内，不会像跨类 getattr/setattr
        搬运那样静默漏绑。

        Args:
            session: 成员并行 turn 专用的独立 db 会话。

        Returns:
            绑定新会话的 AgentChatService 分身。
        """
        from novamind.features.agent.attachments.text_reader import AttachmentTextReader
        from novamind.features.agent.services.host_knowledge_search import (
            HostKnowledgeSearchPort,
        )
        from novamind.features.agent.services.host_memory_store import HostMemoryStorePort

        fork = AgentChatService.__new__(AgentChatService)
        fork.db = session
        fork.agent_service = AgentService(session)
        fork.model_config_service = ModelConfigService(session)
        fork.agent_engine = self.agent_engine
        fork._todo_store = self._todo_store
        fork._memory_search_repo = self._memory_search_repo
        fork._minio_client = self._minio_client
        # db 持有者：重建并绑定到分身 session
        fork._memory_store_port = HostMemoryStorePort(session)
        # ES 记忆仓储持进程级 ES 客户端，不绑 db 会话，直接共享
        fork._memory_search_port = self._memory_search_port
        fork._knowledge_search_port = (
            HostKnowledgeSearchPort(session, fork.model_config_service)
            if self._knowledge_search_port is not None
            else None
        )
        fork._attachment_read_port = (
            AttachmentTextReader(session)
            if self._attachment_read_port is not None
            else None
        )
        fork._web_search_port = self._web_search_port
        fork._prompt_provider = self._prompt_provider
        fork.msg_repo = MessageRepository(session)
        fork.tc_repo = ToolCallRepository(session)
        fork.session_repo = SessionRepository(session)
        fork.attachment_repo = ChatAttachmentRepository(session)
        # 与主实例共享（无 db 状态，且避免深访 agent_engine 内部结构）
        fork._prompt_builder = self._prompt_builder
        return fork






    # ==================== 系统提示辅助 ====================








    # ==================== 记忆注入 ====================


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





    # ==================== 技能指令注入 ====================


    # ==================== 来源提取 ====================


    # ==================== 事件处理 ====================











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
