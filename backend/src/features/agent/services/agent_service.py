"""
Agent 管理服务

负责 Agent 定义和会话的 CRUD。
"""
from datetime import datetime

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
        from novamind.features.agent.models.agent import AgentMessage, AgentSession
        from novamind.features.agent.models.memory import AgentMemory
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
                compaction_items = [
                    self._derive_compaction_response(s)
                    for s in summaries
                    if s.created_at is not None
                    and page_start is not None
                    and page_end is not None
                    and page_start <= s.created_at <= page_end
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
        await self.session_repo.update(
            conversation_id,
            message_count=conv.message_count + 1,
            total_tokens_used=conv.total_tokens_used + tokens,
        )

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
