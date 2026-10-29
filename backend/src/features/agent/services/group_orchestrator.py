"""群聊编排器：用户消息触发一响编排（拉起式），复用 AgentEngine 零改动内核。

两种模式：
- brainstorm：全体成员并行发言 R 轮（默认 1，上限 3）——CC 式多智能体并发，
  每 wave 全员同时拉起（各自独立 AsyncSession），公开发言在 wave 间广播全员，
  成员间经信箱投递通信（send_group_message/send_direct_message 工具即时投递）。
- consult：主持人（host_agent_id）一次完整 ReAct turn，非主持人成员包装为
  consult_member_{id} 工具按需拉起（串行，非主持人一个接一个经工具拉起）。

上下文模型：每 (群会话, 成员) 一条私有 AgentSession（extra_config.group_member
={group_id, group_session_id} 标记），投递=向成员会话 append user 消息
（extra.delivery 标注来源与可见性）；群时间线是投影（仅渲染/审计），不参与
成员上下文组装。一群可开多个群会话，各会话的成员上下文互不可见。
"""
import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.core.ws import envelope
from novamind.engines.agent.agent_engine import AgentEngine  # noqa: F401 类型引用
from novamind.engines.agent.memory.context_scrubber import StreamingContextScrubber
from novamind.engines.agent.memory.short_term import sanitize_user_content
from novamind.engines.agent.tool.base import ToolContext
from novamind.features.agent.exceptions import AgentError, AgentNotFoundError
from novamind.features.agent.models.agent import AgentDefinition
from novamind.features.agent.models.group import AgentGroup, AgentGroupRun
from novamind.features.agent.models.session import AgentSession
from novamind.features.agent.repository.agent_repository import SessionRepository
from novamind.features.agent.repository.group_repository import (
    GroupRepository,
    GroupRunRepository,
)
from novamind.features.agent.services.agent_service import AgentService
from novamind.features.agent.services.chat_service import AgentChatService
from novamind.features.agent.tool.builtins.consult_member import (
    CONSULT_CONTEXT_KEY,
    CONSULT_FN_KEY,
    CONSULT_MEMBERS_KEY,
    ConsultMemberTool,
)
from novamind.features.agent.tool.builtins.consult_member import (
    TOOL_NAME as CONSULT_TOOL_NAME,
)
from novamind.features.agent.tool.builtins.group_messaging import (
    MESSAGING_CONTEXT_KEY,
    MESSAGING_FN_KEY,
    MESSAGING_MEMBERS_KEY,
)
from novamind.shared.prompts.prompt_manager import PromptManager
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)


class MemberTurnError(Exception):
    """单成员 turn 执行失败（引擎 error 事件转译），由调用方失败隔离消化。"""

# 编排参数默认值（extra_config 可覆盖；上限为设计硬约束非资源假设）
DEFAULT_ROUNDS_PER_TURN = 1
MAX_ROUNDS_PER_TURN = 3
# consult 答复回流主持人的截断长度（字符）：全文在成员会话与群时间线可查
DEFAULT_MAX_CONSULT_RESULT_CHARS = 8000
# 成员私有会话 extra_config 标记键
GROUP_MEMBER_FLAG = "group_member"
# 群会话 extra_config 标记键
GROUP_FLAG = "group"
# 头脑风暴发信工具名（事件分流用）
MESSAGING_TOOL_NAMES = ("send_group_message", "send_direct_message")
# 时间线投影 extra 内工具结果的截断上限（字符）：与前端显示截断同口径，信息零损失；
# 全文以 AgentToolCall.result 为准。思考流不截断——投影是其唯一持久化副本。
TIMELINE_TOOL_RESULT_MAX_CHARS = 2000


def _cap_tool_result(text: str) -> str:
    """工具结果按投影显示口径截断（标记样式与前端 truncate 一致）。"""
    if len(text) <= TIMELINE_TOOL_RESULT_MAX_CHARS:
        return text
    return text[:TIMELINE_TOOL_RESULT_MAX_CHARS] + "\n…（已截断）"


def _fork_session(main_session: AsyncSession) -> AsyncSession:
    """从主 session 的 bind 新开一条独立 AsyncSession（并行成员 turn 专用）。

    AsyncSession 不可被并发任务共享（内部连接/事务状态单主）；每成员 fork
    一条，turn 结束即 close 归还连接池。bind 取自主 session（生产=全局引擎
    连接池；测试=夹具的 SQLite 内存库），不碰全局工厂——测试夹具工厂与全局
    工厂不同源，fork 若走全局会连错库。
    """
    sessionmaker = async_sessionmaker(
        bind=main_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return sessionmaker()


class GroupOrchestrator:
    """群聊一响编排"""

    def __init__(
        self,
        db: AsyncSession,
        chat_service: AgentChatService,
    ):
        """装配仓储与单聊服务（组合复用其上下文构建/模型解析/落库/压缩能力）。"""
        self.db = db
        self.chat_service = chat_service
        self.agent_service: AgentService = chat_service.agent_service
        self.group_repo = GroupRepository(db)
        self.run_repo = GroupRunRepository(db)
        self.session_repo = SessionRepository(db)
        # consult 期间成员 turn 事件的暂存队列：consult 工具回调在主持人 turn
        # 的引擎循环内部执行，事件无法直接 yield 给外层生成器，先入队由
        # run_round 在主持人每轮迭代边界统一 flush 转发
        self._consult_events: list[dict[str, Any]] = []

    # ==================== 一响编排入口 ====================

    async def run_round(
        self,
        group: AgentGroup,
        group_session: AgentSession,
        run: AgentGroupRun,
        user_content: str,
        steering_queue: Any | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行一响编排，产出事件流（dict 事件，经群 WS 端点转发）。

        Args:
            group: 群实体。
            group_session: 群会话（时间线所在）。
            run: 已创建的 run 实体（status=running）。
            user_content: 用户消息正文（调用方已完成消毒）。
            steering_queue: 运行中插话队列（透传当前发言成员 turn）。

        Yields:
            事件字典：session/group.speaker/content/reasoning/tool_call/
            tool_result/notice/group.run_done/error 等类型。

        Raises:
            AgentNotFoundError: 群成员 Agent 已被删除。
        """
        members = await self._load_members(group.id)
        config = group.extra_config or {}
        try:
            members = await self._attach_sessions(group, members, group_session.session_id)
            # wave 0：用户消息广播全员私有会话（纯 DB append，无 LLM）
            for m in members:
                await self._deliver(
                    m["session"], from_="user", content=user_content,
                    visibility="group", run_id=run.id,
                )
            # 用户侧消息与新建会话提前提交（防长事务，照抄 chat_service 惯例）
            await self.db.commit()

            yield self._emit("session", {"session_id": group_session.session_id})

            if group.mode == "consult":
                async for ev in self._run_consult(
                    group, group_session, run, members, config, user_content, steering_queue
                ):
                    # consult 期间成员 turn 事件暂存在队列里，主持人的
                    # content/tool 事件之间插入转发（前端流式渲染不断流）
                    while self._consult_events:
                        yield self._consult_events.pop(0)
                    yield ev
                while self._consult_events:
                    yield self._consult_events.pop(0)
            else:
                async for ev in self._run_brainstorm(
                    group, group_session, run, members, config, steering_queue
                ):
                    yield ev
        except (asyncio.CancelledError, GeneratorExit):
            # 客户端断连/取消：run 置 cancelled。rollback 会 expire 全部已加载
            # 实例（后续 run.id 属性访问触发同步 IO 报 MissingGreenlet），先取 id
            run_id = run.id
            await self.db.rollback()
            try:
                await self.run_repo.finish_run(run_id, "cancelled")
                await self.db.commit()
            except Exception as cleanup_err:
                logger.warning("取消时 run 收尾失败", error=str(cleanup_err))
                await self.db.rollback()
            raise
        except Exception as e:
            # 通用兜底：编排层未捕获异常同样收尾 run，防其永久卡 running
            # 阻塞并发护栏（该群从此无法再发起讨论）
            run_id = run.id
            await self.db.rollback()
            try:
                await self.run_repo.finish_run(run_id, "failed", error=str(e))
                await self.db.commit()
            except Exception as cleanup_err:
                logger.warning("异常时 run 收尾失败", error=str(cleanup_err))
                await self.db.rollback()
            raise

    # ==================== 头脑风暴 ====================

    async def _run_brainstorm(
        self,
        group: AgentGroup,
        group_session: AgentSession,
        run: AgentGroupRun,
        members: list[dict[str, Any]],
        config: dict[str, Any],
        steering_queue: Any | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """头脑风暴：每 wave 全体成员并行发言（CC 式并发），公开发言 wave 间广播。

        成员各自在独立 AsyncSession 上跑完整 ReAct turn（AsyncSession 不可并发
        共享，用全局 session factory 每成员新开）；事件经汇流队列转发保持 WS
        单连接时序。沉默者后续轮跳过；单成员失败记 notice 后继续（失败隔离）；
        全部成员全程无有效产出才置 run=failed。
        """
        rounds = min(
            int(config.get("rounds_per_turn") or DEFAULT_ROUNDS_PER_TURN),
            MAX_ROUNDS_PER_TURN,
        )
        spoken_any = False
        silent: set[int] = set()
        speech_log: list[dict[str, Any]] = []
        budget = _TokenBudget(config.get("max_round_tokens"))
        stopped_early = False

        for wave in range(rounds):
            if stopped_early:
                break
            active = [
                m for m in members
                if not (wave > 0 and m["agent_id"] in silent)
            ]
            if not active:
                break
            if budget.exceeded:
                yield self._emit("notice", {
                    "content": "已达到单响 token 预算，本轮讨论提前结束",
                    "run_id": run.id,
                })
                break
            for m in active:
                yield self._emit("group.speaker", {
                    "member_agent_id": m["agent_id"],
                    "name": m["name"],
                    "wave": wave + 1,
                    "run_id": run.id,
                })

            # 全员并发拉起：每成员独立 session+运行时，事件写入共享汇流队列
            merger: asyncio.Queue = asyncio.Queue()
            tasks: dict[int, asyncio.Task] = {}
            for m in active:
                tasks[m["agent_id"]] = asyncio.create_task(
                    self._run_member_turn_detached(
                        group, run, m, members,
                        steering_queue=steering_queue, merger=merger,
                    ),
                    name=f"group-member-{m['agent_id']}",
                )
            try:
                # 汇流消费：成员事件实时转发（WS 单连接时序不变）；哨兵 None=该成员落定
                settled = 0
                while settled < len(tasks):
                    ev = await merger.get()
                    if ev is None:
                        settled += 1
                        continue
                    yield ev

                # 全部落定：先 await 收敛任务（哨兵入队时任务可能还差最后一步
                # 收尾，直接 result() 会撞 InvalidStateError），再收集结果
                results: dict[int, dict[str, Any]] = {}
                errors: dict[int, BaseException] = {}
                for aid, t in tasks.items():
                    try:
                        results[aid] = await t
                    except (asyncio.CancelledError, GeneratorExit):
                        raise
                    except Exception as e:
                        errors[aid] = e

                # wave 串行点：全部成员落定后统一处理（时间线/投递/预算，主 session 独占）
                for m in active:
                    aid = m["agent_id"]
                    if aid in errors:
                        logger.error(
                            "成员发言失败", group_id=group.id,
                            member_agent_id=aid, error=str(errors[aid]),
                        )
                        text = f"成员「{m['name']}」发言失败，已跳过"
                        await self._append_timeline(
                            group_session, m, text, extra={"error": True}
                        )
                        yield self._emit("notice", {"content": text, "run_id": run.id})
                        silent.add(aid)
                        await self.db.commit()
                        continue
                    r = results.get(aid) or {}
                    speech = str(r.get("speech") or "")
                    process = r.get("process") or {}
                    if not speech.strip():
                        silent.add(aid)
                        continue
                    spoken_any = True
                    speech_log.append({
                        "member_agent_id": aid, "name": m["name"], "wave": wave + 1,
                    })
                    await self._append_timeline(group_session, m, speech, process=process)
                    # 公开发言广播其他成员（信箱投递，下一 wave 可见；无 LLM）
                    for other in members:
                        if other["agent_id"] != aid:
                            await self._deliver(
                                other["session"], from_=m["name"], content=speech,
                                visibility="group", run_id=run.id,
                            )
                    await self.db.commit()
                    budget.add(speech)
            finally:
                # 断连/取消：终止仍在跑的成员任务并回收（防任务/session 泄漏）
                for t in tasks.values():
                    if not t.done():
                        t.cancel()
                for t in tasks.values():
                    try:
                        await t
                    except BaseException:
                        pass
                while not merger.empty():
                    merger.get_nowait()

        status = "done" if spoken_any else "failed"
        error = None if spoken_any else "全部成员无有效发言"
        await self.run_repo.finish_run(
            run.id, status, error=error,
            orchestration_meta={"speeches": speech_log, "rounds": rounds},
        )
        await self.db.commit()
        yield self._emit("group.run_done", {
            "run_id": run.id, "status": status, "rounds": rounds,
        })

    async def _run_member_turn_detached(
        self,
        group: AgentGroup,
        run: AgentGroupRun,
        member: dict[str, Any],
        members: list[dict[str, Any]],
        steering_queue: Any | None,
        merger: asyncio.Queue,
    ) -> dict[str, Any]:
        """并行 wave 内单成员独立运行时执行：fork session/服务，事件汇入队列。

        Returns:
            {"speech": 最终发言, "process": 过程档案}；失败抛异常由 wave 串行点
            统一失败隔离。
        """
        session = _fork_session(self.db)
        try:
            orch = self._fork_runtime(session)
            speech = ""
            process: dict[str, Any] = {}
            try:
                async for ev, acc in orch._run_member_turn(
                    group, run, member, members,
                    steering_queue=steering_queue, process_out=process,
                ):
                    merger.put_nowait(ev)
                    speech = acc
                # fork session 事务自管：成员 turn 内的落库（消息/工具卡）
                # 只 flush 不 commit（照抄单聊惯例），此处统一提交；主 session
                # 的 wave 串行点只提交时间线/投递，两边行不相交
                await session.commit()
            except BaseException:
                # 成员任务内异常：回滚自身 session 防连接池脏状态，再上抛隔离
                try:
                    await session.rollback()
                except Exception:
                    pass
                raise
            return {"speech": speech, "process": process}
        finally:
            # 哨兵在所有退出路径（含 fork 失败/取消）保证恰好一条，
            # 消费循环按 len(tasks) 收哨兵不会卡死
            merger.put_nowait(None)
            await session.close()

    def _fork_runtime(self, session: AsyncSession) -> "GroupOrchestrator":
        """在给定 session 上装配编排器分身（成员并行 turn 专用）。

        AsyncSession 不可并发共享：每成员一条独立 session，其上的全部仓储/
        服务/端口（db 持有者）逐一新建重绑；引擎与 prompt 构建器等无 db 状态
        的协作方直接共享。
        """
        src = self.chat_service
        from novamind.features.agent.attachments.repository import (
            ChatAttachmentRepository,
        )
        from novamind.features.agent.attachments.text_reader import AttachmentTextReader
        from novamind.features.agent.repository.agent_repository import (
            AgentRepository,
            McpServerRepository,
            MessageRepository,
            SessionRepository,
            ToolCallRepository,
        )
        from novamind.features.agent.repository.context_summary_repository import (
            ContextSummaryRepository,
        )
        from novamind.features.agent.repository.memory_repository import MemoryRepository
        from novamind.features.agent.services.host_knowledge_search import (
            HostKnowledgeSearchPort,
        )
        from novamind.features.agent.services.host_memory_store import HostMemoryStorePort
        from novamind.features.user.repository.model_config_repository import (
            ModelConfigRepository,
        )
        from novamind.features.user.services.model_config_service import ModelConfigService

        agent_service = AgentService.__new__(AgentService)
        agent_service.db = session
        agent_service.agent_repo = AgentRepository(session)
        agent_service.session_repo = SessionRepository(session)
        agent_service.msg_repo = MessageRepository(session)
        agent_service.tc_repo = ToolCallRepository(session)
        agent_service.memory_repo = MemoryRepository(session)
        agent_service.context_summary_repo = ContextSummaryRepository(session)
        agent_service._mcp_repo = McpServerRepository(session)
        chat2 = AgentChatService.__new__(AgentChatService)
        chat2.db = session
        chat2.agent_service = agent_service
        chat2.agent_engine = src.agent_engine
        chat2._todo_store = src._todo_store
        chat2._memory_search_repo = src._memory_search_repo
        chat2._minio_client = src._minio_client
        chat2._web_search_port = src._web_search_port
        chat2._prompt_provider = src._prompt_provider
        # db 持有者：按类型重绑到 fork session
        chat2._memory_store_port = HostMemoryStorePort(session)
        chat2._knowledge_search_port = (
            HostKnowledgeSearchPort(session, src.model_config_service)
            if src._knowledge_search_port is not None else None
        )
        chat2._attachment_read_port = (
            AttachmentTextReader(session)
            if src._attachment_read_port is not None else None
        )
        mcs = ModelConfigService.__new__(ModelConfigService)
        mcs.db = session
        mcs.repo = ModelConfigRepository(session)
        chat2.model_config_service = mcs
        chat2._memory_search_port = src._memory_search_port
        chat2._prompt_builder = src._prompt_builder
        chat2.tc_repo = agent_service.tc_repo
        chat2.msg_repo = agent_service.msg_repo
        chat2.session_repo = agent_service.session_repo
        chat2.attachment_repo = ChatAttachmentRepository(session)
        for name in (
            "_build_context", "_resolve_model", "_create_memory_manager",
            "_compress_messages", "_build_embedding_resolver",
            "_build_research_service_factory", "_filter_visible_mcp_ids",
        ):
            setattr(chat2, name, getattr(src, name))
        orch = GroupOrchestrator.__new__(GroupOrchestrator)
        orch.db = session
        orch.chat_service = chat2
        orch.agent_service = agent_service
        orch.group_repo = GroupRepository(session)
        orch.run_repo = GroupRunRepository(session)
        orch.session_repo = agent_service.session_repo
        orch._consult_events = []
        return orch

    # ==================== 专家咨询 ====================

    async def _run_consult(
        self,
        group: AgentGroup,
        group_session: AgentSession,
        run: AgentGroupRun,
        members: list[dict[str, Any]],
        config: dict[str, Any],
        user_content: str,
        steering_queue: Any | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """专家咨询：主持人一次完整 ReAct turn，经 consult_member_{id} 工具按需拉起成员。

        成员 turn 事件入 _consult_events 队列（由 run_round 在主持人事件间隙
        flush 转发）；成员答复全文上时间线并广播，截断后作为 tool_result 回流。
        """
        host = next((m for m in members if m.get("is_host")), None)
        if host is None:
            raise AgentError("群缺少主持人（host_agent_id 无效或已被移出成员）")
        consultable = [m for m in members if not m.get("is_host")]
        consulted: list[dict[str, Any]] = []
        speech = ""
        max_chars = int(
            config.get("max_consult_result_tokens") or DEFAULT_MAX_CONSULT_RESULT_CHARS
        )

        async def consult_fn(member_id: int, question: str) -> str:
            """consult 工具回调：拉起成员完整 turn（复用 _run_member_turn），答复截断回流。

            成员 turn 事件暂存 _consult_events；答复同时落时间线并广播其他成员。
            """
            member = next((m for m in members if m["agent_id"] == member_id), None)
            if member is None:
                return f"错误：成员 {member_id} 不在本群成员名单内"
            try:
                speech = ""
                process: dict[str, Any] = {}
                async for ev, acc in self._run_member_turn(
                    group, run, member, members,
                    extra_user_content=question, process_out=process,
                ):
                    self._consult_events.append(ev)
                    speech = acc
                await self.db.commit()
            except Exception as e:
                logger.error("consult 成员 turn 失败", member_agent_id=member_id, error=str(e))
                consulted.append({"member_id": member_id, "question": question[:100], "ok": False})
                return (
                    f"成员「{member['name']}」处理失败：{e}。"
                    "可换其他成员或自行回答。"
                )
            consulted.append({"member_id": member_id, "question": question[:100], "ok": True})
            answer = speech.strip() or "（成员未给出文本答复）"
            # 成员答复上时间线 + 广播其他成员（含主持人——主持人会在自身
            # 会话里看到成员发言全文，与 tool_result 互为备份）
            await self._append_timeline(group_session, member, answer, process=process)
            for other in members:
                if other["agent_id"] != member_id:
                    await self._deliver(
                        other["session"], from_=member["name"], content=answer,
                        visibility="group", run_id=run.id,
                    )
            await self.db.commit()
            if len(answer) > max_chars:
                return answer[:max_chars] + (
                    f"\n\n[答复已截断（全文 {len(answer)} 字符），完整内容见群时间线]"
                )
            return answer

        bundle = {
            CONSULT_FN_KEY: consult_fn,
            CONSULT_MEMBERS_KEY: [
                {"agent_id": m["agent_id"], "name": m["name"], "role_hint": m["role_hint"]}
                for m in consultable
            ],
        }
        yield self._emit("group.speaker", {
            "member_agent_id": host["agent_id"], "name": host["name"],
            "wave": 1, "run_id": run.id,
        })
        host_process: dict[str, Any] = {}
        try:
            async for ev, acc in self._run_member_turn(
                group, run, host, members,
                consult_bundle=bundle, consultable=consultable,
                steering_queue=steering_queue, process_out=host_process,
            ):
                yield ev
                speech = acc
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception as e:
            logger.error("主持人 turn 失败", group_id=group.id, error=str(e))
            await self.run_repo.finish_run(
                run.id, "failed", error=str(e)[:500],
                orchestration_meta={"consulted": consulted},
            )
            await self.db.commit()
            yield self._emit("error", {"content": f"主持人处理失败：{e}", "run_id": run.id})
            return

        if speech.strip():
            await self._append_timeline(group_session, host, speech, process=host_process)
        await self.run_repo.finish_run(
            run.id, "done", orchestration_meta={"consulted": consulted},
        )
        await self.db.commit()
        yield self._emit("group.run_done", {"run_id": run.id, "status": "done", "rounds": 1})

    # ==================== 成员 turn（两模式共用） ====================

    async def _run_member_turn(
        self,
        group: AgentGroup,
        run: AgentGroupRun,
        member: dict[str, Any],
        members: list[dict[str, Any]],
        extra_user_content: str | None = None,
        consult_bundle: dict[str, Any] | None = None,
        consultable: list[dict[str, Any]] | None = None,
        steering_queue: Any | None = None,
        process_out: dict[str, Any] | None = None,
    ) -> AsyncGenerator[tuple[dict[str, Any], str], None]:
        """拉起单成员一次完整 ReAct turn（复用 AgentEngine.run），落库照抄 chat_service。

        Args:
            member: 成员 dict（agent/agent_id/name/role_hint/session）。
            members: 全体成员（群身份 prompt 派生 + 发信收件人校验）。
            extra_user_content: consult 场景成员收到的触发问题（附加投递进其会话）。
            consult_bundle: 非空时本成员为主持人，注入 consult_member 工具与回调。
            consultable: 主持人可咨询成员清单（动态工具 schema 生成源）。
            steering_queue: 运行中插话队列。
            process_out: 非空 dict 时在 done 处装配过程档案（tools/reasoning），
                供调用方并入时间线投影（历史回放复原工具卡与思考区）。

        Yields:
            (事件字典, 累计最终答复) 二元组；done 事件对应的累计值即最终发言。
        """
        agent: AgentDefinition = member["agent"]
        conv: AgentSession = member["session"]
        # fork 运行时的成员 turn：agent/conv 等 ORM 实体来自主 session，须并入
        # 本 session 才能持久化操作（merge load=False 按 id 复制为受管副本；
        # turn 内写的是消息/工具卡等新行，不回写这两个实体）
        if inspect(conv).session is not self.db:
            conv = await self.db.merge(conv, load=False)
            member = {**member, "session": conv}
        user_id = group.user_id
        model = await self.chat_service._resolve_model(user_id, agent, None)
        memory_manager = await self.chat_service._create_memory_manager(
            agent, user_id, model, conv.id,
            self.chat_service._memory_store_port, self.chat_service._memory_search_port,
            self.chat_service._prompt_provider,
        )

        # consult 成员：触发问题作为投递进其私有会话（与 wave0 用户消息同构）
        if extra_user_content:
            await self._deliver(
                conv, from_="主持人", content=extra_user_content,
                visibility="group", run_id=run.id,
            )
            await self.db.commit()

        llm_client, tools, messages, _snapshot, _prompt, caps = (
            await self.chat_service._build_context(
                agent, conv, user_id, model, "", memory_manager,
            )
        )
        # user_content 传空：触发消息（用户原话/consult 问题）已在 build_context
        # 之前以投递形式 commit 进成员会话，MemoryManager 会将其组装进 messages，
        # 无需二次注入。_build_context 内部已按会话工作区绑定强制并入
        # local_workspace 勾选并生成工作目录 prompt——群聊成员与单聊同口径。

        context = ToolContext(
            db_session=self.db, user_id=user_id,
            agent_id=member["agent_id"], session_id=conv.session_id,
        ).to_dict()
        context["conversation_id"] = conv.id
        context["tool_result_turn_budget"] = 100_000
        # 成员能力与单聊全量对齐：勾了 task/research 就接子代理/研究工厂。
        # 嵌套放大由 agent 自身 max_tool_calls_per_turn 与引擎迭代上限约束。
        if "task" in (agent.enabled_tools or []):
            from novamind.engines.agent.subagent import SubAgentRunner

            context["subagent_runner"] = SubAgentRunner(
                agent_engine=self.chat_service.agent_engine,
                tool_executor=self.chat_service.agent_engine.tool_executor,
                client_factory=self.chat_service._subagent_client_factory(user_id),
                model=model,
                enabled_tools=agent.enabled_tools or [],
                enabled_mcp_ids=await self.chat_service._filter_visible_mcp_ids(
                    user_id, agent.enabled_mcp_servers or []
                ),
                parent_context=context,
            )
        else:
            context["subagent_runner"] = None
        context["research_service_factory"] = (
            await self.chat_service._build_research_service_factory()
            if "research" in (agent.enabled_tools or [])
            else None
        )
        context["web_search_port"] = self.chat_service._web_search_port
        context["knowledge_search_port"] = self.chat_service._knowledge_search_port
        # 本地工作区端口：群会话绑定工作区即注入（绑定本身即授权，工具默认必带）
        if (conv.extra_config or {}).get("workspace"):
            from novamind.features.agent.services.local_workspace.assembly import (
                build_local_workspace_port,
            )

            context["local_workspace_port"] = await build_local_workspace_port(
                self.db, user_id, conv
            )
        else:
            context["local_workspace_port"] = None
        context["knowledge_pipeline"] = {
            "llm_client": llm_client,
            "knowledge_bindings": (conv.extra_config or {}).get("knowledge_bindings"),
            "conversation_history": [],
        }
        context["attachment_read_port"] = self.chat_service._attachment_read_port
        context["memory_store_port"] = self.chat_service._memory_store_port
        context["memory_search_port"] = self.chat_service._memory_search_port
        context["embedding_client_resolver"] = self.chat_service._build_embedding_resolver(user_id)
        context["approval_registry"] = None
        context["event_sink"] = None

        is_host = consult_bundle is not None
        if is_host:
            context[CONSULT_CONTEXT_KEY] = consult_bundle
        else:
            context[MESSAGING_CONTEXT_KEY] = {
                MESSAGING_FN_KEY: self._make_messaging_fn(run, member, members, group),
                MESSAGING_MEMBERS_KEY: [
                    {"agent_id": m["agent_id"], "name": m["name"]}
                    for m in members if m["agent_id"] != member["agent_id"]
                ],
            }

        # 工具列表：成员自有工具；主持人用带成员 enum 的 consult 定义覆盖静态同名项
        if caps.tools and is_host and consultable:
            consult_def = ConsultMemberTool.tool_def([
                {"agent_id": m["agent_id"], "name": m["name"], "role_hint": m["role_hint"]}
                for m in consultable
            ])
            if consult_def is not None:
                tools = [
                    t for t in tools
                    if t.get("function", {}).get("name") != CONSULT_TOOL_NAME
                ] + [consult_def]

        # 群身份段追加到 system 消息尾部（组装后原地修改，engine 直接消费）
        identity = self._build_identity_prompt(group, member, members, is_host)
        for msg in messages:
            if msg.get("role") == "system":
                msg["content"] = (msg.get("content") or "") + "\n\n" + identity
                break

        full_response = ""
        scrubber = StreamingContextScrubber()
        speech = ""
        assistant_msg_id: int | None = None
        # 本轮发言的过程档案：工具步骤与思考流，随时间线投影持久化（历史回放复原用）
        turn_tools: list[dict[str, Any]] = []
        turn_reasoning = ""

        async def _compress_on_overflow(msgs):
            """溢出兜底压缩回调（透传 tools，照抄 chat_service）。"""
            return await self.chat_service._compress_messages(
                msgs, memory_manager, model,
                agent.context_window or 32768, conv.id, tools=tools,
            )

        try:
            async for event in self.chat_service.agent_engine.run(
                llm_client=llm_client,
                messages=messages,
                tools=tools,
                context=context,
                stream=True,
                enable_thinking=False,
                max_iterations=agent.max_tool_calls_per_turn or 5,
                max_tokens=agent.max_tokens or 2048,
                temperature=agent.temperature if agent.temperature is not None else 0.7,
                top_p=agent.top_p if agent.top_p is not None else 0.8,
                compress_fn=_compress_on_overflow,
                steering_queue=steering_queue,
            ):
                if "iteration" in event.data:
                    context["current_iteration"] = event.data.get("iteration")
                if event.event_type == "assistant_tool_calls":
                    msg = await self.agent_service.save_message(
                        conversation_id=conv.id, role="assistant",
                        content=event.data.get("content") or None,
                        extra={"tool_calls": event.data.get("tool_calls", [])},
                        iteration=context.get("current_iteration"),
                    )
                    assistant_msg_id = msg.id
                    context["assistant_msg_id"] = msg.id
                elif event.event_type == "tool_call":
                    tc = await self.chat_service.tc_repo.create(
                        message_id=assistant_msg_id or 0,
                        conversation_id=conv.id,
                        call_id=event.data.get("call_id") or None,
                        tool_name=event.data.get("tool_name", ""),
                        tool_source="builtin",
                        arguments=event.data.get("arguments", {}),
                        status="running",
                        iteration=context.get("current_iteration"),
                    )
                    context[f"tc_{event.data.get('call_id')}"] = tc.id
                    turn_tools.append({
                        "call_id": event.data.get("call_id") or "",
                        "tool_name": event.data.get("tool_name", ""),
                        "arguments": event.data.get("arguments", {}),
                        "status": "running",
                    })
                    # 落库后转发给 WS（口径同单聊 chat_service）：前端工具卡实时翻转状态
                    yield self._member_event(event.event_type, member, dict(event.data)), full_response
                elif event.event_type == "tool_result":
                    call_id = event.data.get("call_id", "")
                    tc_id = context.get(f"tc_{call_id}")
                    full_result = event.data.get("full_result", "")
                    if tc_id:
                        await self.chat_service.tc_repo.update(
                            tc_id,
                            result=full_result,
                            status=event.data.get("status", "completed"),
                            duration_ms=event.data.get("duration_ms"),
                        )
                    await self.agent_service.save_message(
                        conversation_id=conv.id, role="tool",
                        content=event.data.get("result", "") or full_result,
                        tool_call_id=call_id,
                        tool_name=event.data.get("tool_name"),
                        iteration=context.get("current_iteration"),
                    )
                    for step in reversed(turn_tools):
                        if step["call_id"] == call_id:
                            step["result"] = _cap_tool_result(full_result)
                            step["status"] = (
                                "failed" if event.data.get("status") == "failed" else "completed"
                            )
                            break
                    yield self._member_event(event.event_type, member, dict(event.data)), full_response
                elif event.event_type == "content":
                    cleaned = scrubber.feed(event.data.get("content", ""))
                    full_response += cleaned
                    if cleaned:
                        yield self._member_event(event.event_type, member, {"content": cleaned}), full_response
                elif event.event_type == "reasoning":
                    turn_reasoning += event.data.get("content", "")
                    yield self._member_event(event.event_type, member, {
                        "content": event.data.get("content", ""),
                    }), full_response
                elif event.event_type == "done":
                    remaining = scrubber.flush()
                    if remaining:
                        full_response += remaining
                    if event.data.get("truncated", False):
                        full_response += "\n\n[已达到最大迭代次数，发言被截断]"
                    speech = full_response
                    if process_out is not None:
                        process_out["tools"] = turn_tools
                        process_out["reasoning"] = turn_reasoning or ""
                    await self._finish_member_turn(conv, agent, event, speech, context)
                    yield self._member_event("done", member, {
                        "content": speech,
                        "total_tokens": event.data.get("total_tokens", 0),
                    }), speech
                elif event.event_type == "error":
                    # 引擎层错误（如模型额度耗尽）以 raise 退出本 turn，交给
                    # 调用方的成员失败隔离（notice+跳过/consult 错误回流），
                    # 不能只转发——前端 onError 会断连导致整响中断、run 卡死
                    raise MemberTurnError(str(event.data.get("content", "成员执行出错")))
        except (asyncio.CancelledError, GeneratorExit):
            # 断连/取消：回滚未提交事务（投递与 user 消息已提前 commit）
            try:
                await self.db.rollback()
            except Exception:
                pass
            raise

    async def _finish_member_turn(
        self,
        conv: AgentSession,
        agent: AgentDefinition,
        event: Any,
        speech: str,
        context: dict[str, Any],
    ) -> None:
        """成员 turn 收尾：最终 assistant 落库 + 会话统计 + 标题（flush，调用方 commit）。"""
        total_tokens = event.data.get("total_tokens", 0)
        done_extra: dict[str, Any] = {}
        if event.data.get("last_iteration_usage"):
            done_extra["usage"] = event.data["last_iteration_usage"]
        await self.agent_service.save_message(
            conversation_id=conv.id, role="assistant",
            content=speech, token_count=total_tokens,
            extra=done_extra or None,
            iteration=context.get("current_iteration"),
        )
        await self.agent_service.update_session_stats(conv.id, total_tokens)
        await self.db.refresh(conv)
        if conv.message_count <= 1 and not conv.title:
            await self.session_repo.update(conv.id, title=(agent.name or "群成员")[:50])

    # ==================== 群发信工具回调 ====================

    def _make_messaging_fn(
        self,
        run: AgentGroupRun,
        member: dict[str, Any],
        members: list[dict[str, Any]],
        group: AgentGroup,
    ):
        """构造 group_messaging 工具回调：闭包持有编排上下文，工具执行期直接落投递。

        send_group_message 需要上群时间线（时间线在编排器侧按最终发言统一落，
        工具侧群发只做投递到其他成员私有会话——时间线以 turn 最终答复为准，
        工具中途群发文本视为过程性投递，可被收件人提前看到）。
        """

        async def fn(tool_name: str, arguments: dict[str, Any]) -> str:
            content = str(arguments.get("content") or "").strip()
            if not content:
                return json.dumps({"error": "内容不能为空"})
            if tool_name == "send_group_message":
                for other in members:
                    if other["agent_id"] != member["agent_id"]:
                        await self._deliver(
                            other["session"], from_=member["name"], content=content,
                            visibility="group", run_id=run.id,
                        )
                await self.db.commit()
                return json.dumps({"ok": True, "delivered": "group"})
            # send_direct_message：收件人合法性已由工具侧校验
            to_member = int(arguments.get("to_member"))
            target = next(
                (m for m in members if m["agent_id"] == to_member), None
            )
            if target is None:
                return json.dumps({"error": f"成员 {to_member} 不在同组成员名单内"})
            await self._deliver(
                target["session"], from_=member["name"], content=content,
                visibility="direct", run_id=run.id,
            )
            await self.db.commit()
            return json.dumps({"ok": True, "delivered": "direct"})

        return fn

    # ==================== 投递/时间线/会话 ====================

    async def _deliver(
        self,
        session: AgentSession,
        from_: str,
        content: str,
        visibility: str,
        run_id: int,
    ) -> None:
        """投递：向成员私有会话 append user 消息，extra.delivery 标注来源/可见性。

        内容包裹 <delivery> 标签并先经 sanitize_user_content 消毒（成员发言
        可被注入污染，与用户消息同防线）；from_ 同样转义防伪造标签属性。
        """
        safe = sanitize_user_content(content)
        safe_from = str(from_).replace("<", "&lt;").replace('"', "&quot;")
        wrapped = f'<delivery from="{safe_from}" visibility="{visibility}">{safe}</delivery>'
        await self.agent_service.save_message(
            conversation_id=session.id, role="user", content=wrapped,
            extra={"delivery": {"from": from_, "visibility": visibility, "run_id": run_id}},
        )

    async def _append_timeline(
        self,
        group_session: AgentSession,
        member: dict[str, Any],
        speech: str,
        extra: dict[str, Any] | None = None,
        process: dict[str, Any] | None = None,
    ) -> None:
        """公开发言落群时间线（投影）：role=assistant + extra.member_agent_id。

        process（本轮工具步骤+思考流）非空时并入 extra.process——时间线是
        该发言过程的唯一持久化副本（工具调用记录挂在成员私有会话，群回放
        不读那边），刷新后的历史回放据此复原工具卡与思考折叠区。
        """
        payload: dict[str, Any] = {
            "member_agent_id": member["agent_id"], "name": member["name"],
        }
        if process and (process.get("tools") or process.get("reasoning")):
            payload["process"] = {
                "tools": process.get("tools") or [],
                "reasoning": process.get("reasoning") or "",
            }
        if extra:
            payload.update(extra)
        await self.agent_service.save_message(
            conversation_id=group_session.id, role="assistant",
            content=speech, extra=payload,
        )

    async def _load_members(self, group_id: int) -> list[dict[str, Any]]:
        """加载群成员（含 Agent 定义）；成员 Agent 已删则整响失败（能力缺失优于错拉）。"""
        rows = await self.group_repo.list_members(group_id)
        members: list[dict[str, Any]] = []
        for member_row, agent_name in rows:
            agent = await self.agent_service.agent_repo.get_by_id(member_row.agent_id)
            if agent is None:
                raise AgentNotFoundError(member_row.agent_id)
            members.append({
                "agent_id": member_row.agent_id,
                "name": agent_name or agent.name or f"成员{member_row.agent_id}",
                "role_hint": member_row.role_hint,
                "agent": agent,
                "is_host": False,
            })
        return members

    async def _attach_sessions(
        self, group: AgentGroup, members: list[dict[str, Any]],
        group_session_id: str,
    ) -> list[dict[str, Any]]:
        """为每个成员 get_or_create 私有会话，并按 host_agent_id 标记主持人。

        会话 extra_config.group_member={group_id, group_session_id} 标记归属
        ——按 (群, 群会话) 二元组隔离：一个群开多个会话时，各会话的成员
        上下文互不可见（对齐设计文档数据模型节）；与该 agent 的单聊会话
        完全隔离。
        """
        for m in members:
            if group.host_agent_id == m["agent_id"]:
                m["is_host"] = True
            existing = await self._find_member_session(
                group.id, group_session_id, m["agent_id"]
            )
            if existing is not None:
                m["session"] = existing
                continue
            session = await self.session_repo.create(
                user_id=group.user_id, agent_id=m["agent_id"],
                extra_config={
                    GROUP_MEMBER_FLAG: {
                        "group_id": group.id,
                        "group_session_id": group_session_id,
                    }
                },
            )
            m["session"] = session
        await self.db.commit()
        return members

    async def _find_member_session(
        self, group_id: int, group_session_id: str, agent_id: int
    ) -> AgentSession | None:
        """按 (group_id, group_session_id, agent_id) 查活跃成员私有会话。

        只认双键齐备的会话：历史数据（仅 group_id，无 group_session_id）
        不匹配即新建，旧上下文不串入新会话。
        """
        from sqlalchemy import select

        stmt = (
            select(AgentSession)
            .where(
                AgentSession.agent_id == agent_id,
                AgentSession.extra_config[GROUP_MEMBER_FLAG]["group_id"].as_integer() == group_id,
                AgentSession.extra_config[GROUP_MEMBER_FLAG]["group_session_id"].as_string()
                == group_session_id,
                AgentSession.status == "active",
            )
            .order_by(AgentSession.id.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    def _build_identity_prompt(
        self,
        group: AgentGroup,
        member: dict[str, Any],
        members: list[dict[str, Any]],
        is_host: bool,
    ) -> str:
        """构造群身份段 prompt（agent_group_identity 模板渲染，失败退化最小声明）。"""
        others = [
            {"name": m["name"], "role_hint": m["role_hint"] or ""}
            for m in members if m["agent_id"] != member["agent_id"]
        ]
        if is_host:
            mode_hint = "专家咨询模式，你是主持人：判断问题后用 consult_member_数字 工具咨询合适的成员，可多次咨询不同成员，最后综合给出答复；问题简单时可自行回答"
        elif group.mode == "consult":
            mode_hint = "专家咨询模式，你是被咨询成员：完整回答交给你的问题"
        else:
            mode_hint = (
                "头脑风暴模式：全体成员同时发言（并行讨论），不等他人结束；"
                "想私下交流特定成员用 send_direct_message 工具，"
                "想中途向全体补充观点用 send_group_message 工具；"
                "其他成员的发言与私信会作为消息送达你（信箱投递），"
                "当前这轮先独立给出你的观点，后续轮可回应他人"
            )
        try:
            return PromptManager.format_prompt(
                "agent_group_identity",
                group_name=group.name,
                my_name=member["name"],
                role_hint=member.get("role_hint") or "（无补充描述）",
                mode_hint=mode_hint,
                members_json=json.dumps(others, ensure_ascii=False),
            )
        except Exception as e:
            logger.warning("群身份 prompt 渲染失败，退化为最小声明", error=str(e))
            return (
                f"<group-context>\n你是群「{group.name}」中的成员「{member['name']}」。\n"
                "</group-context>"
            )

    def _member_event(
        self, event_type: str, member: dict[str, Any], data: dict[str, Any]
    ) -> dict[str, Any]:
        """成员事件统一加 member_agent_id/name 标记后构造 envelope。"""
        payload = {"member_agent_id": member["agent_id"], "name": member["name"], **data}
        return envelope(event_type, payload)

    def _emit(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """构造统一事件 envelope。"""
        return envelope(event_type, data)


class _TokenBudget:
    """单响 token 预算护栏（字符×2 近似口径，超限即停，已发言内容保留）。"""

    def __init__(self, max_tokens: Any):
        try:
            self.max_chars = int(max_tokens) * 2 if max_tokens else None
        except (TypeError, ValueError):
            self.max_chars = None
        self.used = 0

    @property
    def exceeded(self) -> bool:
        return self.max_chars is not None and self.used >= self.max_chars

    def add(self, text: str) -> None:
        self.used += len(text)
