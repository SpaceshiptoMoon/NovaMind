"""
压缩时长期记忆提取的 arq 后台任务。

write-before-compaction 的异步形态：压缩流程不再同步等待 consolidate 的 LLM
提取调用，而是把即将丢弃的轮次序列化后投递到嵌入式 worker 执行；入队失败由
压缩器侧退回同步路径（见 context_compressor._extract_memories）。
"""
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


async def consolidate_memory_task(
    ctx: dict,
    agent_id: int,
    user_id: int,
    conversation_id: int,
    turns: list[dict],
    model: str,
) -> None:
    """从被压缩丢弃的轮次中提取长期记忆（与同步路径同参数语义）。

    Args:
        ctx: arq 任务上下文（job_id 等，未用）。
        agent_id: Agent ID（记忆归属与 ES 索引命名空间）。
        user_id: 用户 ID（记忆归属与模型配置解析）。
        conversation_id: 来源会话 ID，0 表示未知。
        turns: MemoryMessage.asdict() 列表（JSON 反序列化后的 dict 形态）。
        model: 对话主模型名，决定 token 计数口径与 LLM 连接参数。
    """
    from novamind.core.database.database import get_session_factory
    from novamind.engines.agent.memory.interfaces import MemoryMessage
    from novamind.engines.agent.memory.long_term import LongTermMemory
    from novamind.features.agent.services.host_memory_store import HostMemoryStorePort
    from novamind.features.user.services.model_config_service import ModelConfigService
    from novamind.shared.prompts.prompt_manager import PromptManager

    session = get_session_factory()()
    try:
        mcs = ModelConfigService(session)
        memory_store = HostMemoryStorePort(session)

        # ES 检索端口：不可用时置空（LongTermMemory 内部降级 MySQL LIKE，
        # embedding 工厂不传则跳过向量化——与请求路径的降级语义一致）
        memory_search = None
        try:
            from novamind.features.agent.repository.memory_search_repository import (
                MemorySearchRepository,
            )
            from novamind.shared.storage.client_factory import get_elasticsearch_client

            es_wrapper = await get_elasticsearch_client()
            memory_search = MemorySearchRepository(es_client=es_wrapper.es_client)
        except Exception as e:
            logger.warning("记忆提取任务 ES 端口装配失败，降级无向量提取", error=str(e))

        async def llm_factory():
            try:
                return await mcs.get_llm_client_by_model(user_id, model)
            except Exception:
                return await mcs.get_vlm_client_by_model(user_id, model)

        async def embedding_factory():
            embedding_model = await mcs.get_user_default_model_name(user_id, "embedding")
            if not embedding_model:
                raise RuntimeError("未配置 embedding 模型")
            return await mcs.get_embedding_client_by_model(user_id, embedding_model)

        reconciler = None
        from novamind.setting.yaml_config import get_config
        if get_config().agent.memory.backend == "mem0":
            try:
                from novamind.features.agent.services.chat_service import AgentChatService

                reconciler = await AgentChatService._build_memory_reconciler(
                    model_config_service=mcs,
                    user_id=user_id,
                    agent_id=agent_id,
                    memory_store=memory_store,
                    memory_search=memory_search,
                    embedding_factory=embedding_factory if memory_search else None,
                )
            except Exception as e:
                logger.warning("Mem0 reconciler 装配失败，降级 builtin", error=str(e))

        long_term = LongTermMemory(
            memory_store,
            llm_factory,
            prompt_provider=PromptManager(),
            memory_search=memory_search,
            embedding_factory=embedding_factory if memory_search else None,
            reconciler=reconciler,
        )
        stored = await long_term.consolidate(
            agent_id=agent_id,
            user_id=user_id,
            conversation_id=conversation_id or 0,
            messages=[MemoryMessage(**t) for t in turns],
            min_turns=2,
            max_recent_turns=len(turns),
        )
        if stored > 0:
            logger.info(
                "压缩时记忆提取完成（异步）",
                agent_id=agent_id, user_id=user_id,
                conversation_id=conversation_id, stored=stored, turns=len(turns),
            )
    except Exception as e:
        # write-before-compaction 语义下任务失败即本轮提取丢失，与同步路径的
        # except-and-log 行为一致，arq 默认重试由 max_tries 兜底
        logger.warning(
            "压缩时记忆提取失败（异步）",
            agent_id=agent_id, conversation_id=conversation_id, error=str(e),
        )
    finally:
        await session.close()
