"""
记忆子系统装配：MemoryManager / Mem0 调和器的唯一组装点。

此前装配逻辑散在三处各自为政：chat_service 私有方法（_create_memory_manager/
_build_memory_reconciler）、GroupOrchestrator 经 setattr 搬运私有方法转调、
arq 任务（memory_tasks）反向 import chat_service 私有静态方法——本模块收口
后三处共用同一公共函数。配置读取（agent.memory 配置节）收在本层，引擎侧
（engines/agent/memory）零 setting import 的边界不变。
"""
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.agent.memory.interfaces import IMemorySearch, IMemoryStore
from novamind.engines.agent.memory.memory_manager import MemoryManager
from novamind.features.agent.models.agent import AgentDefinition
from novamind.features.agent.services.context_assembly import (
    build_embedding_resolver,
    build_llm_vlm_client_factory,
)
from novamind.features.agent.services.host_knowledge_search import (
    HostKnowledgeSearchPort,  # noqa: F401  类型引用（装配签名文档化）
)
from novamind.features.agent.services.host_memory_store import (
    HostMemorySearchPort,
    HostMemoryStorePort,
)
from novamind.features.user.exceptions import ModelConfigNotFoundError
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.setting.yaml_config.loader import get_config
from novamind.shared.prompts.prompt_manager import PromptManager
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def build_memory_reconciler(
    model_config_service: ModelConfigService,
    user_id: int,
    agent_id: int,
    memory_store: HostMemoryStorePort,
    memory_search: HostMemorySearchPort | None,
    embedding_factory: Any | None = None,
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


async def create_memory_manager(
    db: AsyncSession,
    model_config_service: ModelConfigService,
    *,
    agent: AgentDefinition,
    user_id: int,
    model: str,
    conversation_id: int,
    memory_store: IMemoryStore,
    memory_search: IMemorySearch | None,
    prompt_provider: PromptManager,
    todo_store: Any | None = None,
) -> MemoryManager:
    """创建请求级 MemoryManager 实例（单聊/群聊/arq 任务共用的唯一装配点）。

    Args:
        db: 请求级数据库会话（消息/工具调用/会话三个仓储绑定其上）。
        model_config_service: 模型配置服务（LLM/embedding 客户端解析）。
        agent: Agent 定义（记忆归属命名空间）。
        user_id: 用户 ID。
        model: 会话模型名（token 计数口径与压缩 LLM）。
        conversation_id: 会话主键 ID。
        memory_store: MySQL 真源读写端口（长期记忆 + 摘要同端口）。
        memory_search: ES hybrid 端口，可空（ES 不可用时检索降级 MySQL）。
        prompt_provider: prompt 注册表（压缩/提取模板）。
        todo_store: 压缩后任务重注入存储，可空。

    Returns:
        组装完成的 MemoryManager。
    """
    from novamind.features.agent.repository.agent_repository import (
        MessageRepository,
        SessionRepository,
        ToolCallRepository,
    )

    llm_factory = build_llm_vlm_client_factory(model_config_service, user_id)
    embedding_factory = build_embedding_resolver(model_config_service, user_id)

    # 辅助模型：用于压缩摘要，优先用更便宜的模型（当前与主模型同源，留差异位）
    auxiliary_llm_factory = llm_factory

    reconciler = None
    if get_config().agent.memory.backend == "mem0":
        try:
            reconciler = await build_memory_reconciler(
                model_config_service=model_config_service,
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
        message_repository=MessageRepository(db),
        tool_call_repository=ToolCallRepository(db),
        session_repository=SessionRepository(db),
        long_term_store=memory_store,
        summary_store=memory_store,
        prompt_provider=prompt_provider,
        model=model,
        llm_client_factory=llm_factory,
        memory_search=memory_search,
        embedding_factory=embedding_factory if memory_search else None,
        todo_store=todo_store,
        conversation_id=conversation_id,
        agent_id=agent.id,
        user_id=user_id,
        auxiliary_llm_factory=auxiliary_llm_factory,
        reconciler=reconciler,
        memory_compaction_async=_memory_flag("compaction_async"),
        memory_on_turn_done=_memory_flag("on_turn_done"),
    )


def _memory_flag(key: str) -> bool:
    """读 agent.memory 配置节的布尔开关（缺节/缺键一律 False）。"""
    try:
        return bool(getattr(get_config().agent.memory, key, False))
    except Exception:
        return False


__all__ = [
    "build_memory_reconciler",
    "create_memory_manager",
]
