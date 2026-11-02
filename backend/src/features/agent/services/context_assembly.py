"""
工具执行上下文装配：单聊（AgentChatService）与群聊（GroupOrchestrator）共用的
单一组装点。

背景：context 组装逻辑此前散在两条路径各自手工重复 17 个 key，且已漂移 3 处
（群聊 web_search_port 不做勾选裁剪、approval/event_sink 语义含糊、
knowledge_pipeline 形状不一致）。本模块收口为唯一装配函数——构造端收口，
消费端（工具/引擎）只见强类型 ToolContext。

引擎端口与凭证解析的业务依赖（模型配置/DB 归属校验）在此层注入，引擎侧
（engines/agent）零感知。
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.agent.agent_engine import AgentEngine
from novamind.engines.agent.tool.context import ToolContext
from novamind.engines.agent.tool.ports import KnowledgePipelineConfig
from novamind.features.agent.models.agent import AgentDefinition
from novamind.features.agent.models.session import AgentSession
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.setting.yaml_config.loader import get_config
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


@dataclass
class ChatPorts:
    """请求级引擎端口束（由装配点 dependencies.build_agent_chat_service 构造）。

    群聊 fork 场景下按新 session 重建后传入，成员 turn 与单聊同口径。
    """

    web_search_port: Any | None = None
    knowledge_search_port: Any | None = None
    memory_store_port: Any | None = None
    memory_search_port: Any | None = None
    attachment_read_port: Any | None = None


def build_llm_vlm_client_factory(
    model_config_service: ModelConfigService, user_id: int
) -> Callable[[str], Any]:
    """构造 LLM 客户端工厂（LLM 优先、VLM 兜底；业务降级策略闭包在此，不进引擎）。

    供 SubAgentRunner 的 client_factory 与记忆压缩 llm_factory 共用。
    """
    mcs = model_config_service

    async def factory(model: str):
        try:
            return await mcs.get_llm_client_by_model(user_id, model)
        except Exception:
            return await mcs.get_vlm_client_by_model(user_id, model)

    return factory


def build_embedding_resolver(
    model_config_service: ModelConfigService, user_id: int
) -> Callable[[], Any]:
    """构造 embedding 客户端 resolver（供 memory 工具 ES 索引与 MemoryManager
    embedding_factory 共用，同源同口径）。"""
    mcs = model_config_service

    async def resolver():
        embedding_model = await mcs.get_user_default_model_name(user_id, "embedding")
        if not embedding_model:
            raise RuntimeError("未配置 embedding 模型")
        return await mcs.get_embedding_client_by_model(user_id, embedding_model)

    return resolver


async def filter_visible_mcp_ids(
    db: AsyncSession, user_id: int, raw_ids: list[int]
) -> list[int]:
    """过滤掉当前用户不可见（他人私有）的 MCP 服务器 id。

    聊天路径的失败方向安全：历史数据可能含越权 id（归属校验前落库），
    此处静默剔除并告警而非抛错——能力缺失优于杀死进行中的会话。

    Args:
        db: 请求级数据库会话。
        user_id: 当前用户 ID。
        raw_ids: agent 配置的 MCP 服务器 id 列表。

    Returns:
        仅含可见（自有或系统级）服务器 id 的列表。
    """
    if not raw_ids:
        return []
    from novamind.features.agent.repository.agent_repository import McpServerRepository

    visible = {s.id for s in await McpServerRepository(db).list_by_user(user_id)}
    filtered = [i for i in raw_ids if i in visible]
    dropped = [i for i in raw_ids if i not in visible]
    if dropped:
        logger.warning(
            "agent 启用了不可见的 MCP 服务器，已在本次会话中剔除",
            user_id=user_id, dropped_mcp_ids=dropped,
        )
    return filtered


async def build_research_service_factory(
    model_config_service: ModelConfigService,
) -> Callable[[], Any]:
    """构造 DeepResearchService 工厂（供 research 工具经 ToolContext 调用）。

    每次调用构造独立服务实例：db session 用全局工厂新开（研究内部 rollback /
    错误恢复不得连坐外层 chat 事务）、ES 客户端经 shared/storage 客户端工厂取
    单例（与 web 适配层 dependencies 同款装配）。
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
            model_config_service=model_config_service,
            es_client=es_client,
        )

    return factory


def _agent_memory_int(key: str) -> int | None:
    """读 agent.memory 配置节的整型值（缺节/缺键/类型不符一律 None）。"""
    try:
        value = getattr(get_config().agent.memory, key, None)
        return int(value) if value is not None else None
    except Exception:
        return None


async def build_tool_context(
    db: AsyncSession,
    *,
    user_id: int,
    agent: AgentDefinition,
    session: AgentSession,
    conversation_id: int,
    session_id: str | None,
    model: str,
    llm_client: Any,
    conversation_history: list[dict[str, str]] | None,
    ports: ChatPorts,
    model_config_service: ModelConfigService,
    agent_engine: AgentEngine,
    approval_registry: Any | None = None,
    event_sink: Any | None = None,
) -> ToolContext:
    """组装单次对话请求的 ToolContext（唯一装配点）。

    端口条件注入口径：
    - web_search_port：仅 Agent 勾选 web_search 时下发（没选不兜底）；
    - local_workspace_port：会话绑定工作区即注入（绑定本身即授权，工具默认必带）；
    - subagent_runner：仅勾选 task 时构造（parent_context 自引用最终对象）；
    - research_service_factory：仅勾选 research 时构造；
    - knowledge_pipeline：会话无绑定时仍注入（管线质量层默认生效），仅范围为不限定；
    - approval_registry/event_sink：WS 单聊通道传入，群聊等无审批通道场景恒 None
      （审批钩子按「无通道告警放行」降级）。

    Args:
        db: 请求级数据库会话。
        user_id: 当前用户 ID。
        agent: Agent 定义（enabled_tools 门控）。
        session: 会话实体（extra_config 承载工作区绑定与知识绑定）。
        conversation_id: 会话主键 ID。
        session_id: 业务会话 ID（子 agent 场景 None）。
        model: 已解析的会话模型名（SubAgentRunner 构造用）。
        llm_client: 会话模型客户端（knowledge 管线改写/打分用）。
        conversation_history: 知识管线改写用的最近对话（单聊传最近 6 条，群聊传 []）。
        ports: 请求级端口束。
        model_config_service: 模型配置服务（客户端工厂与 embedding 解析）。
        agent_engine: 应用级单例引擎（SubAgentRunner 构造用）。
        approval_registry: 异步审批注册表，可空。
        event_sink: 旁路事件接收器，可空。

    Returns:
        组装完成的 ToolContext。
    """
    enabled_tools = list(agent.enabled_tools or [])

    context = ToolContext(
        db_session=db,
        user_id=user_id,
        agent_id=agent.id,
        session_id=session_id,
        conversation_id=conversation_id,
        web_search_port=ports.web_search_port if "web_search" in enabled_tools else None,
        knowledge_search_port=ports.knowledge_search_port,
        memory_store_port=ports.memory_store_port,
        memory_search_port=ports.memory_search_port,
        attachment_read_port=ports.attachment_read_port,
        approval_registry=approval_registry,
        event_sink=event_sink,
        memory_limit_per_user_agent=_agent_memory_int("memory_limit_per_user_agent"),
    )

    # 本地工作区端口：会话绑定即注入（不要求 agent 单独勾选）
    if (session.extra_config or {}).get("workspace"):
        from novamind.features.agent.services.local_workspace.assembly import (
            build_local_workspace_port,
        )

        context.local_workspace_port = await build_local_workspace_port(
            db, user_id, session
        )

    # 知识检索质量管线配置：改写/打分与会话主回答同模型
    context.knowledge_pipeline = KnowledgePipelineConfig(
        llm_client=llm_client,
        knowledge_bindings=(session.extra_config or {}).get("knowledge_bindings"),
        conversation_history=list(conversation_history or []),
    )

    # E6 子 agent 委派：勾选 task 时注入 SubAgentRunner（parent_context 引用最终
    # 对象；子代理执行时经 dataclasses.replace 派生并置 None 防递归）
    if "task" in enabled_tools:
        from novamind.engines.agent.subagent import SubAgentRunner

        context.subagent_runner = SubAgentRunner(
            agent_engine=agent_engine,
            tool_executor=agent_engine.tool_executor,
            client_factory=build_llm_vlm_client_factory(model_config_service, user_id),
            model=model,
            enabled_tools=enabled_tools,
            enabled_mcp_ids=await filter_visible_mcp_ids(
                db, user_id, agent.enabled_mcp_servers or []
            ),
            parent_context=context,
        )

    # 深度研究（批3）：勾选 research 时注入请求级服务工厂
    if "research" in enabled_tools:
        context.research_service_factory = await build_research_service_factory(
            model_config_service
        )

    return context


__all__ = [
    "ChatPorts",
    "build_embedding_resolver",
    "build_llm_vlm_client_factory",
    "build_research_service_factory",
    "build_tool_context",
    "filter_visible_mcp_ids",
]
