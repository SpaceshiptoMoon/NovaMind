"""
Agent 管理服务

负责 Agent 定义和会话的 CRUD。
"""
from datetime import datetime
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent.exceptions import (
    AgentNotFoundError,
    McpServerError,
    MemoryNotFoundError,
    SessionNotFoundError,
)
from novamind.features.agent.models.agent import AgentDefinition
from novamind.features.agent.models.context_summary import AgentContextSummary
from novamind.features.agent.models.message import AgentMessage
from novamind.features.agent.models.session import AgentSession
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
from novamind.features.agent.schemas.agent_schema import (
    AgentCreate,
    AgentDetailResponse,
    AgentListResponse,
    AgentMessageResponse,
    AgentResponse,
    AgentSessionListResponse,
    AgentSummary,
    AgentUpdate,
    MemoryListResponse,
    MemoryResponse,
    MemoryStatsResponse,
    MessageListResponse,
    SessionResponse,
    ToolCallResponse,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# 默认助手内置工具基线：ensure 幂等更新时对 is_default 行做并集补齐
# （版本演进新增工具时，存量默认助手在下次 ensure 自动获得）
_DEFAULT_AGENT_TOOLS = [
    "knowledge_search",
    "web_search",
    "memory",
    "todo",
    "task",
    "read_attachment",
    "research",
]


class AgentService:
    """Agent 管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.agent_repo = AgentRepository(db)
        self.session_repo = SessionRepository(db)
        self.msg_repo = MessageRepository(db)
        self.tc_repo = ToolCallRepository(db)
        self.memory_repo = MemoryRepository(db)
        self.context_summary_repo = ContextSummaryRepository(db)
        self._mcp_repo = McpServerRepository(db)

    async def _validate_mcp_ids(self, user_id: int, mcp_ids: list[int] | None) -> None:
        """校验 enabled_mcp_servers 只含当前用户可见的服务器 id（自有或系统级）。

        enabled_mcp_servers 原样落库会被用来从全局连接缓存按 id 借用他人
        MCP 服务器（含其 headers/凭证），必须在写入口做归属校验。

        Args:
            user_id: 当前用户 ID。
            mcp_ids: 待校验的服务器 id 列表，空/None 直接放行。

        Raises:
            McpServerError: 含任何不可见（他人私有）服务器 id。
        """
        if not mcp_ids:
            return
        visible = {s.id for s in await self._mcp_repo.list_by_user(user_id)}
        invalid = [i for i in mcp_ids if i not in visible]
        if invalid:
            raise McpServerError(
                message=f"启用了不可用的 MCP 服务器: {invalid}",
                code="MCP_SERVER_IDS_INVALID",
            )

    # ==================== Agent CRUD ====================

    async def create_agent(self, user_id: int, data: AgentCreate) -> AgentDetailResponse:
        """创建 Agent 并提交事务，返回详情响应。

        Args:
            user_id: 属主用户 ID。
            data: 创建参数（名称/系统提示词/模型/采样参数/启用工具与 MCP 服务器等）。

        Returns:
            新建 Agent 的详情响应模型。

        Raises:
            McpServerError: enabled_mcp_servers 含不可见（他人私有）服务器 id。
        """
        await self._validate_mcp_ids(user_id, data.enabled_mcp_servers)
        agent = await self.agent_repo.create(
            user_id=user_id,
            name=data.name,
            description=data.description,
            system_prompt=data.system_prompt,
            llm_model=data.llm_model,
            max_tokens=data.max_tokens,
            context_window=data.context_window,
            temperature=data.temperature,
            top_p=data.top_p,
            max_tool_calls_per_turn=data.max_tool_calls_per_turn,
            enabled_tools=data.enabled_tools,
            enabled_mcp_servers=data.enabled_mcp_servers,
            extra_config=data.extra_config,
        )
        await self.db.commit()
        return AgentDetailResponse.model_validate(agent)

    async def get_agent(self, user_id: int, agent_id: int) -> AgentDetailResponse:
        """按归属校验取 Agent 详情响应，未命中或非本人抛 AgentNotFoundError。

        Args:
            user_id: 当前用户 ID，系统级 Agent 对所有用户可见。
            agent_id: Agent 主键 ID。

        Returns:
            Agent 详情响应模型。

        Raises:
            AgentNotFoundError: Agent 不存在，或私有 Agent 非属主。
        """
        agent = await self.get_agent_or_fail(user_id, agent_id)
        return AgentDetailResponse.model_validate(agent)

    async def get_agent_definition(
        self, user_id: int, agent_id: int
    ) -> "AgentDefinition":
        """获取 Agent ORM 对象（供 chat_service 等需要原始模型的场景使用）。

        Args:
            user_id: 当前用户 ID，系统级 Agent 对所有用户可见。
            agent_id: Agent 主键 ID。

        Returns:
            AgentDefinition ORM 实体。

        Raises:
            AgentNotFoundError: Agent 不存在，或私有 Agent 非属主。
        """
        return await self.get_agent_or_fail(user_id, agent_id)

    async def get_agent_or_fail(self, user_id: int, agent_id: int) -> "AgentDefinition":
        """取 Agent ORM 实体并做归属校验（系统级对所有用户可见），失败抛 AgentNotFoundError。

        Args:
            user_id: 当前用户 ID，系统级 Agent 对所有用户可见。
            agent_id: Agent 主键 ID。

        Returns:
            通过归属校验的 AgentDefinition ORM 实体。

        Raises:
            AgentNotFoundError: Agent 不存在，或私有 Agent 非属主。
        """
        agent = await self.agent_repo.get_by_id(agent_id)
        if not agent or (agent.user_id is not None and agent.user_id != user_id):
            raise AgentNotFoundError(agent_id)
        return agent

    # ==================== 跨 feature 公共面（skill 消费，原 HostAgentRegistryPort 语义） ====================

    async def get_agent_summary(self, agent_id: int) -> AgentSummary | None:
        """按 id 取 Agent 摘要（不含归属校验，供技能广场安装/卸载侧查询）。

        Args:
            agent_id: Agent 主键 ID。

        Returns:
            Agent 摘要（id/user_id/enabled_tools），Agent 不存在时返回 None。
        """
        agent = await self.agent_repo.get_by_id(agent_id)
        if agent is None:
            return None
        return AgentSummary(
            id=agent.id,
            user_id=agent.user_id,
            enabled_tools=list(agent.enabled_tools or []),
        )

    async def update_agent_enabled_tools(self, agent_id: int, enabled_tools: list) -> None:
        """更新 Agent 启用工具集（供技能广场安装/卸载后写回）。

        Args:
            agent_id: Agent 主键 ID。
            enabled_tools: 新的启用工具名列表，整体替换原集合。

        Returns:
            无；仅 flush 不 commit，事务由调用方收口。
        """
        await self.agent_repo.update(agent_id, enabled_tools=enabled_tools)

    async def ensure_default_agent(self, user_id: int) -> AgentDetailResponse:
        """确保用户拥有默认助手（幂等），无则创建并返回详情。

        默认助手是普通私有 agent（user_id=user_id），extra_config.is_default=true 标记；
        用户删除后再次调用会重建。私有行而非系统级：系统级会出现在所有用户的列表且
        仅管理员可编辑，语义不对。

        Args:
            user_id: 归属用户 ID。

        Returns:
            默认助手的详情响应。

        Raises:
            McpServerError: 理论不可达（默认助手不挂 MCP），保留以对齐创建路径契约。
        """
        # SQL 层 JSON 精确匹配（MySQL/SQLite JSON_EXTRACT），不依赖分页窗口
        existing = await self.db.execute(
            select(AgentDefinition).where(
                AgentDefinition.user_id == user_id,
                AgentDefinition.extra_config["is_default"].as_boolean().is_(True),
            )
        )
        agent = existing.scalar_one_or_none()
        if agent is not None:
            # 存量默认助手补齐新增内置工具（幂等）：seed 之后版本新增的工具并入
            # enabled_tools（当前新增 research）。仅对 is_default 行——默认助手是
            # 系统播种的基线，用户要定制可自建 agent；并集保证用户自行加过的工具不丢
            tools = list(agent.enabled_tools or [])
            missing = [t for t in _DEFAULT_AGENT_TOOLS if t not in tools]
            if missing:
                async with self.db.begin_nested():
                    agent.enabled_tools = tools + missing
                    await self.db.flush()
            return AgentDetailResponse.model_validate(agent)

        await self._validate_mcp_ids(user_id, None)
        async with self.db.begin_nested():
            agent = await self.agent_repo.create(
                user_id=user_id,
                name="个人助手",
                description="内置助手：可检索知识库、联网搜索、深度研究、读取附件",
                system_prompt=(
                    "你是用户的个人助手。回答知识性、时效性问题或需要查资料时，"
                    "优先调用 knowledge_search 或 web_search 工具获取依据后再作答；"
                    "用户要求深入调研、全面分析或横向对比复杂课题时，调用 research "
                    "工具发起深度研究（需数分钟，先告知用户）。"
                    "寒暄、改写、简单解释等无需外部信息的请求直接回答，不调用工具。"
                    "回答基于检索结果时注明来源。"
                ),
                enabled_tools=list(_DEFAULT_AGENT_TOOLS),
                extra_config={"is_default": True},
            )
        return AgentDetailResponse.model_validate(agent)

    async def list_agents(
        self, user_id: int, limit: int = 20, offset: int = 0
    ) -> AgentListResponse:
        """分页列出系统级与用户自有的 Agent，返回含总数的列表响应。

        Args:
            user_id: 当前用户 ID。
            limit: 页大小，默认 20。
            offset: 偏移量，默认 0。

        Returns:
            含 items/total/limit/offset 的列表响应，created_at 倒序。
        """
        agents, total = await self.agent_repo.list_by_user(user_id, limit, offset)
        return AgentListResponse(
            items=[AgentResponse.model_validate(a) for a in agents],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update_agent(
        self, user_id: int, agent_id: int, data: AgentUpdate, is_admin: bool = False
    ) -> AgentDetailResponse:
        """更新 Agent（系统级仅管理员、普通仅属主），空更新直接返回当前详情。

        Args:
            user_id: 当前用户 ID。
            agent_id: Agent 主键 ID。
            data: 更新字段集合，仅显式传入的字段生效。
            is_admin: 是否管理员；系统级 Agent（user_id 为 NULL）须为 True，默认 False。

        Returns:
            更新后的详情响应；data 无变更字段时原样返回当前详情。

        Raises:
            AgentNotFoundError: 不存在、系统级 Agent 非管理员或私有 Agent 非属主。
            McpServerError: enabled_mcp_servers 含不可见（他人私有）服务器 id。
        """
        agent = await self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise AgentNotFoundError(agent_id)
        # 系统级预置 Agent（user_id=None）仅管理员可改；普通 Agent 仅属主可改
        if agent.user_id is None:
            if not is_admin:
                raise AgentNotFoundError(agent_id)
        elif agent.user_id != user_id:
            raise AgentNotFoundError(agent_id)

        update_data = data.model_dump(exclude_unset=True)
        if "enabled_mcp_servers" in update_data:
            # 归属校验用 agent 实际属主而非操作者：系统级 Agent 的 mcp 集合由管理员维护，
            # 但校验基准仍是「谁可见」，系统级 Agent 场景操作者即管理员
            await self._validate_mcp_ids(
                agent.user_id if agent.user_id is not None else user_id,
                update_data["enabled_mcp_servers"],
            )
        if update_data:
            agent = await self.agent_repo.update(agent_id, **update_data)
            await self.db.commit()

        return AgentDetailResponse.model_validate(agent)

    async def delete_agent(self, user_id: int, agent_id: int, is_admin: bool = False) -> None:
        """删除 Agent 并级联清理工具调用、消息、会话与长期记忆，最后提交事务。

        Args:
            user_id: 当前用户 ID。
            agent_id: Agent 主键 ID。
            is_admin: 是否管理员；系统级 Agent（user_id 为 NULL）须为 True，默认 False。

        Returns:
            无。

        Raises:
            AgentNotFoundError: 不存在、系统级 Agent 非管理员或私有 Agent 非属主。
        """
        from novamind.features.agent.models.memory import AgentMemory
        from novamind.features.agent.models.message import AgentMessage
        from novamind.features.agent.models.session import AgentSession
        from novamind.features.agent.models.tool_call import AgentToolCall

        agent = await self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise AgentNotFoundError(agent_id)
        # 系统级预置 Agent（user_id=None）仅管理员可删；普通 Agent 仅属主可删
        if agent.user_id is None:
            if not is_admin:
                raise AgentNotFoundError(agent_id)
        elif agent.user_id != user_id:
            raise AgentNotFoundError(agent_id)

        # 级联删除关联数据
        from sqlalchemy import delete as sql_delete
        # 1. 工具调用记录（通过 message → session → agent）
        conv_ids_stmt = select(AgentSession.id).where(AgentSession.agent_id == agent_id)
        conv_ids_result = await self.db.execute(conv_ids_stmt)
        conv_ids = [row[0] for row in conv_ids_result.all()]

        if conv_ids:
            await self.db.execute(sql_delete(AgentToolCall).where(AgentToolCall.conversation_id.in_(conv_ids)))
            await self.db.execute(sql_delete(AgentMessage).where(AgentMessage.conversation_id.in_(conv_ids)))

        # 2. 会话
        await self.db.execute(sql_delete(AgentSession).where(AgentSession.agent_id == agent_id))

        # 3. 长期记忆
        await self.db.execute(sql_delete(AgentMemory).where(AgentMemory.agent_id == agent_id))

        # 4. Agent 本身
        await self.agent_repo.delete(agent_id)
        await self.db.commit()

    # ==================== 会话管理 ====================

    async def get_or_create_session(
        self, user_id: int, agent_id: int, session_id: str | None = None
    ) -> AgentSession:
        """带 session_id 时校验归属、所属 Agent 与 active 状态（任一不符抛 SessionNotFoundError），缺省新建会话。

        Args:
            user_id: 当前用户 ID。
            agent_id: Agent 主键 ID。
            session_id: 业务会话 ID；None 时新建会话并提交事务。

        Returns:
            校验通过的既有会话或新建的会话 ORM 实体。

        Raises:
            SessionNotFoundError: 会话不存在、非本人、属于其他 Agent 或已非 active。
        """
        if session_id:
            conv = await self.session_repo.get_by_session_id(session_id)
            if not conv:
                raise SessionNotFoundError(session_id)
            if conv.user_id != user_id:
                raise SessionNotFoundError(session_id)
            if conv.agent_id != agent_id:
                raise SessionNotFoundError(session_id)
            if conv.status != "active":
                raise SessionNotFoundError(session_id)
            return conv

        conv = await self.session_repo.create(user_id=user_id, agent_id=agent_id)
        await self.db.commit()
        return conv

    async def list_sessions(
        self,
        user_id: int,
        agent_id: int | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> AgentSessionListResponse:
        """分页列出用户会话（仅 active），可按 Agent 过滤，返回含总数的列表响应。

        Args:
            user_id: 当前用户 ID。
            agent_id: 按 Agent 过滤，None 列出全部 Agent 的会话。
            limit: 页大小，默认 20。
            offset: 偏移量，默认 0。

        Returns:
            含 items/total 的列表响应，created_at 倒序。
        """
        convs, total = await self.session_repo.list_by_user(
            user_id, agent_id, limit, offset
        )
        return AgentSessionListResponse(
            items=[SessionResponse.model_validate(c) for c in convs],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_session(self, user_id: int, session_id: str) -> AgentSession:
        """按 session_id 取会话并校验归属与 active 状态，失败抛 SessionNotFoundError。

        Args:
            user_id: 当前用户 ID。
            session_id: 业务会话 ID。

        Returns:
            校验通过的会话 ORM 实体。

        Raises:
            SessionNotFoundError: 会话不存在、非本人或已非 active。
        """
        conv = await self.session_repo.get_by_session_id(session_id)
        if not conv or conv.user_id != user_id or conv.status != "active":
            raise SessionNotFoundError(session_id)
        return conv

    async def delete_session(self, user_id: int, session_id: str) -> None:
        """软删会话（status=deleted），未命中抛 SessionNotFoundError。

        Args:
            user_id: 当前用户 ID，防止越权软删他人会话。
            session_id: 业务会话 ID。

        Returns:
            无。

        Raises:
            SessionNotFoundError: 会话不存在或不属于该用户。
        """
        deleted = await self.session_repo.delete(session_id, user_id)
        if not deleted:
            raise SessionNotFoundError(session_id)
        await self.db.commit()

    async def update_session_knowledge_bindings(
        self, user_id: int, session_id: str, knowledge_bindings: dict[str, Any] | None
    ) -> SessionResponse:
        """更新会话级知识绑定（extra_config.knowledge_bindings 整体替换）。

        约束（没选不兜底）：bindings 中声明的 space_ids/kb_ids 必须全部属于该用户
        可访问范围，任一越权即整体拒绝（不做静默过滤——静默丢 ID 会让"看似绑定了
        实际没绑定"的错配不可追踪）。knowledge_bindings=None 清除绑定恢复不限定。

        Args:
            user_id: 当前用户 ID，同时是会话归属与空间/知识库访问校验主体。
            session_id: 业务会话 ID。
            knowledge_bindings: 绑定 dict（KnowledgeBindings 校验后的形态），None 清除。

        Returns:
            更新后的会话响应。

        Raises:
            SessionNotFoundError: 会话不存在或不属于该用户。
            AgentError: 绑定引用了不可访问的空间或知识库。
        """
        conv = await self.get_session(user_id, session_id)

        if knowledge_bindings is not None:
            from novamind.features.agent.exceptions import AgentError
            from novamind.features.knowledge_space.services.access_service import (
                check_space_access,
            )

            space_ids = knowledge_bindings.get("space_ids")
            kb_ids = knowledge_bindings.get("kb_ids")

            if space_ids:
                for sid in space_ids:
                    if not await check_space_access(self.db, sid, user_id):
                        raise AgentError(f"空间 {sid} 不存在或无权访问")

            if kb_ids:
                from novamind.features.knowledge_space.services.knowledge_base_service import (
                    KnowledgeBaseService,
                )
                from novamind.features.knowledge_space.services.space_service import (
                    SpaceService,
                )

                kb_service = KnowledgeBaseService(self.db, es_client=None, minio_client=None)
                space_service = SpaceService(self.db)
                accessible_space_ids = {
                    s.id for s in await space_service.get_user_spaces(user_id)
                }
                for kbid in kb_ids:
                    kb = await kb_service.get_knowledge_base(kbid)
                    if kb is None or kb.space_id not in accessible_space_ids:
                        raise AgentError(f"知识库 {kbid} 不存在或无权访问")

        extra_config = dict(conv.extra_config) if conv.extra_config else {}
        if knowledge_bindings is None:
            extra_config.pop("knowledge_bindings", None)
        else:
            extra_config["knowledge_bindings"] = knowledge_bindings

        async with self.db.begin_nested():
            await self.session_repo.update(conv.id, extra_config=extra_config)
        await self.db.commit()

        await self.db.refresh(conv)
        return SessionResponse.model_validate(conv)

    # ==================== 消息反馈与引用点击（批2：对齐 qa_message_feedback 语义） ====================

    async def _get_message_with_session_check(
        self, user_id: int, message_id: int
    ) -> AgentMessage:
        """按主键取消息并校验归属（经会话归属链），失败统一视为不存在。

        Args:
            user_id: 当前用户 ID。
            message_id: 消息主键 ID。

        Returns:
            校验通过的消息 ORM 实体。

        Raises:
            SessionNotFoundError: 消息不存在或所属会话不属于该用户。
        """
        result = await self.db.execute(
            select(AgentMessage).where(AgentMessage.id == message_id)
        )
        msg = result.scalar_one_or_none()
        if msg is None:
            raise SessionNotFoundError(f"message:{message_id}")
        conv = await self.session_repo.get_by_id(msg.conversation_id)
        if conv is None or conv.user_id != user_id:
            raise SessionNotFoundError(f"message:{message_id}")
        return msg

    async def set_message_feedback(
        self, user_id: int, message_id: int, rating: str | None, comment: str | None
    ) -> dict[str, Any]:
        """设置/撤销消息反馈（点赞/点踩）。

        rating=None 撤销（幂等：无反馈也返回成功）；仅 assistant 消息可反馈且
        必须属于当前用户；写走独立 feedback repository（SAVEPOINT），事务在此提交。

        Args:
            user_id: 当前用户 ID。
            message_id: 被反馈的 assistant 消息 ID。
            rating: up/down，None 撤销。
            comment: 反馈补充说明，None 不改已有评论。

        Returns:
            反馈响应 dict（message_id/rating/comment）。

        Raises:
            SessionNotFoundError: 消息不存在或不属于该用户。
            AgentError: 对非 assistant 消息反馈。
        """
        from novamind.features.agent.exceptions import AgentError
        from novamind.features.agent.repository.message_feedback_repository import (
            MessageFeedbackRepository,
        )

        msg = await self._get_message_with_session_check(user_id, message_id)
        if msg.role != "assistant":
            raise AgentError("只能对 AI 回答反馈")

        feedback_repo = MessageFeedbackRepository(self.db)
        conv = await self.session_repo.get_by_id(msg.conversation_id)
        if rating is None:
            await feedback_repo.delete(message_id, user_id)
            await self.db.commit()
            return {"message_id": message_id, "rating": None, "comment": None}

        await feedback_repo.upsert(
            message_id=message_id,
            user_id=user_id,
            session_id=conv.session_id if conv else "",
            rating=rating,
            comment=comment,
        )
        await self.db.commit()
        return {"message_id": message_id, "rating": rating, "comment": comment}

    async def record_citation_click(
        self, user_id: int, message_id: int, click: dict[str, Any]
    ) -> None:
        """记录引用点击（kb-ops O2：用户核验行为的被动信号）。

        仅 assistant 消息且消息归属人可上报；落账本走 EventRecorder 旁路
        （独立短事务、全异常吞掉），上报失败不影响主流程。幂等性不做——
        同一来源多次点击是真实的重复核验行为，每次都记。space_id 锚点：
        agent 会话无固定空间归属，点击载荷里带 kb_id/document_id 即可归因。

        Args:
            user_id: 当前用户 ID。
            message_id: 被点击引用所属的 assistant 消息 ID。
            click: 点击载荷（source_index/chunk_id/document_id/kb_id）。

        Raises:
            SessionNotFoundError: 消息不存在或不属于该用户。
            AgentError: 对非 assistant 消息上报。
        """
        from novamind.features.agent.exceptions import AgentError

        msg = await self._get_message_with_session_check(user_id, message_id)
        if msg.role != "assistant":
            raise AgentError("只能上报 AI 回答的引用点击")

        conv = await self.session_repo.get_by_id(msg.conversation_id)
        from novamind.features.knowledge_ops.services.event_recorder import EventRecorder

        await EventRecorder().record(
            event_type="citation_click",
            user_id=user_id,
            session_id=conv.session_id if conv else None,
            kb_id=click.get("kb_id"),
            extra={
                "source": "agent",
                "message_id": message_id,
                "source_index": click.get("source_index"),
                "chunk_id": click.get("chunk_id"),
                "document_id": click.get("document_id"),
            },
        )

    # ==================== 消息 ====================

    async def save_message(
        self,
        conversation_id: int,
        role: str,
        content: str | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        token_count: int | None = None,
        extra: dict | None = None,
        reasoning: str | None = None,
        iteration: int | None = None,
    ) -> AgentMessage:
        """落库一条对话消息（flush 不 commit，随对话事务统一提交），返回消息实体。

        Args:
            conversation_id: 会话主键 ID。
            role: 消息角色（user/assistant/tool/notice/plan 等）。
            content: 消息正文，工具调用轮等无正文场景可为 None。
            tool_call_id: 工具调用 ID，仅 role=tool 消息携带。
            tool_name: 工具名，仅工具消息携带。
            token_count: 该消息 token 用量。
            extra: 附加结构化数据（附件引用/工具调用明细/错误标记等）。
            reasoning: 该轮思考过程文本（assistant 决策消息用）。
            iteration: 所属 ReAct 迭代轮号。

        Returns:
            已 flush 的消息 ORM 实体。
        """
        msg = await self.msg_repo.create(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            token_count=token_count,
            extra=extra,
            reasoning=reasoning,
            iteration=iteration,
        )
        await self.db.flush()
        return msg

    async def get_messages(
        self, user_id: int, session_id: str, limit: int = 50, offset: int = 0
    ) -> MessageListResponse:
        """分页取会话消息，附全量工具调用记录，并把压缩摘要按时间窗合并为 compaction 标记行。

        Args:
            user_id: 当前用户 ID，用于会话归属校验。
            session_id: 业务会话 ID。
            limit: 页大小，默认 50。
            offset: 偏移量，默认 0。

        Returns:
            items 为当前页消息（created_at 升序，compaction 标记按时间合并），tool_calls 为会话全量工具调用。

        Raises:
            SessionNotFoundError: 会话不存在、非本人或已非 active。
        """
        conv = await self.get_session(user_id, session_id)
        messages, total = await self.msg_repo.list_by_conversation(
            conv.id, limit, offset
        )
        # 加载会话全部工具调用记录，供前端历史回放工具状态（call_id 与 tool 消息 tool_call_id 对应）
        tool_calls = await self.tc_repo.list_by_conversation(conv.id)
        # 历史回放 compaction 标记：把 agent_context_summaries 派生为 role='compaction'
        # 消息，按 created_at 合并进当前页消息流，刷新/切会话后压缩点仍可见。
        # compaction 稀少（长对话才触发），仅插入 created_at 落在当前页时间窗内的标记。
        items = [AgentMessageResponse.model_validate(m) for m in messages]
        if messages:
            try:
                summaries = await self.context_summary_repo.list_by_conversation(conv.id)
            except Exception as e:
                logger.warning("压缩摘要历史回放查询失败", error=str(e))
                summaries = []
            if summaries:
                page_start = messages[0].created_at
                page_end = messages[-1].created_at
                # 去重：当前页已含实时流推送过的 compaction 消息（SSE/WS onCompaction
                # 前端 push，id 为本地生成大数）时，同一压缩事件会出现两条标记行
                # （实时行 + 本表派生行）。以页内已存在的 compaction 行为准，跳过
                # 时间上贴近的派生行——同页 ±5s 内视为同一事件。
                existing_compaction_times = [
                    m.created_at
                    for m in messages
                    if m.role == "compaction" and m.created_at is not None
                ]

                def _is_duplicate(summary_created: datetime) -> bool:
                    """判断派生行是否为页内已有 compaction 行的同事件重复（±5s 容差）。"""
                    for t in existing_compaction_times:
                        if abs((t - summary_created).total_seconds()) <= 5:
                            return True
                    return False

                compaction_items = [
                    self._derive_compaction_response(s)
                    for s in summaries
                    if s.created_at is not None
                    and page_start is not None
                    and page_end is not None
                    and page_start <= s.created_at <= page_end
                    and not _is_duplicate(s.created_at)
                ]
                if compaction_items:
                    items = sorted(
                        items + compaction_items,
                        key=lambda x: x.created_at or datetime.min,
                    )
        return MessageListResponse(
            items=items,
            total=total,
            tool_calls=[ToolCallResponse.model_validate(tc) for tc in tool_calls],
        )

    def _derive_compaction_response(self, summary: AgentContextSummary) -> AgentMessageResponse:
        """把压缩摘要派生为 role='compaction' 响应消息（不落库，仅历史回放显示）。

        id 用负数避免与真实 AgentMessage.id 冲突；extra.compaction 携带 N 条 + 摘要正文，
        供前端 CompactionItem 渲染标记行与就地展开。
        """
        return AgentMessageResponse(
            id=-(summary.id),
            conversation_id=summary.conversation_id,
            role="compaction",
            content=None,
            created_at=summary.created_at,
            extra={
                "compaction": {
                    "summarized_count": summary.compressed_count,
                    "summary": summary.summary_text,
                    "compression_ratio": summary.compression_ratio,
                }
            },
        )

    async def update_session_stats(
        self, conversation_id: int, tokens: int
    ) -> None:
        """累加会话消息数与 token 用量，会话不存在时静默跳过。

        Args:
            conversation_id: 会话主键 ID。
            tokens: 本次新增的 token 数。

        Returns:
            无。
        """
        conv = await self.session_repo.get_by_id(conversation_id)
        if not conv:
            return
        # SQL 表达式原子自增：读-改-写两步在并发消息下丢计数/丢 token 统计
        await self.session_repo.increment_stats(conversation_id, tokens)

    # ==================== 记忆管理 ====================

    async def list_memories(
        self,
        user_id: int,
        agent_id: int,
        category: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> MemoryListResponse:
        """列出 Agent 的长期记忆（校验 Agent 归属后按 updated_at 倒序分页）。

        Args:
            user_id: 当前用户 ID，用于 Agent 归属校验。
            agent_id: Agent 主键 ID。
            category: 按记忆类别过滤，None 不过滤。
            limit: 页大小，默认 20。
            offset: 偏移量，默认 0。

        Returns:
            含 items/total 的记忆列表响应。

        Raises:
            AgentNotFoundError: Agent 不存在，或私有 Agent 非属主。
        """
        await self.get_agent_or_fail(user_id, agent_id)
        memories, total = await self.memory_repo.list_by_agent(
            agent_id, user_id, category=category, limit=limit, offset=offset,
        )
        return MemoryListResponse(
            items=[MemoryResponse.model_validate(m) for m in memories],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def delete_memory(
        self, user_id: int, agent_id: int, memory_id: int
    ) -> None:
        """删除指定记忆（MySQL + ES）。

        Args:
            user_id: 当前用户 ID，用于归属校验。
            agent_id: Agent 主键 ID。
            memory_id: 记忆主键 ID。

        Returns:
            无；ES 删除失败仅告警，仍删除 MySQL 记录。

        Raises:
            AgentNotFoundError: Agent 不存在，或私有 Agent 非属主。
            MemoryNotFoundError: 记忆不存在、不属于该 Agent 或非本人所有。
        """
        await self.get_agent_or_fail(user_id, agent_id)
        memory = await self.memory_repo.get_by_id(memory_id)
        if not memory or memory.agent_id != agent_id or memory.user_id != user_id:
            raise MemoryNotFoundError(memory_id)

        # 尝试从 ES 删除
        try:
            from novamind.features.agent.repository.memory_search_repository import (
                MemorySearchRepository,
            )
            from novamind.shared.storage.client_factory import ClientFactory
            es_wrapper = await ClientFactory.get_elasticsearch_client()
            search_repo = MemorySearchRepository(es_client=es_wrapper.es_client)
            await search_repo.delete_memory(agent_id, memory_id)
        except Exception as e:
            logger.warning("ES 记忆删除失败，仅删除 MySQL", error=str(e))

        await self.memory_repo.delete(memory_id)
        await self.db.commit()

    async def get_memory_stats(
        self, user_id: int, agent_id: int
    ) -> MemoryStatsResponse:
        """汇总该 Agent 的记忆条数/分类分布统计。

        Args:
            user_id: 当前用户 ID，用于 Agent 归属校验。
            agent_id: Agent 主键 ID。

        Returns:
            总数、按类别计数与最近创建的 5 条记忆。

        Raises:
            AgentNotFoundError: Agent 不存在，或私有 Agent 非属主。
        """
        await self.get_agent_or_fail(user_id, agent_id)
        memories, total = await self.memory_repo.list_by_agent(
            agent_id, user_id, limit=1000,
        )

        by_category: dict[str, int] = {}
        for m in memories:
            by_category[m.category] = by_category.get(m.category, 0) + 1

        recent = sorted(memories, key=lambda m: m.created_at, reverse=True)[:5]

        return MemoryStatsResponse(
            total_memories=total,
            by_category=by_category,
            recently_created=[MemoryResponse.model_validate(m) for m in recent],
        )
