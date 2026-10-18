"""
压缩摘要生成的 arq 后台任务。

压缩任务化的异步形态：压缩流程不再同步等待摘要 LLM 调用，而是把被压缩区
序列化后投递到嵌入式 worker 生成摘要并落库（agent_context_summaries）；
入队失败由压缩器侧退回同步路径（见 context_compressor._enqueue_summary）。
任务落库后，下次 build_context 经 get_latest_summary 消费摘要——异步窗口内
的主循环走静态占位降级（能力缺失优于阻塞）。
"""
import html

from novamind.shared.logging import get_logger
from novamind.shared.utils.redact import redact_sensitive_text

logger = get_logger(__name__)


async def generate_compaction_summary_task(
    ctx: dict,
    conversation_id: int,
    turns: list[dict],
    previous_summary: str | None,
    compressed_count: int,
    compression_ratio: float,
    agent_id: int,
    user_id: int,
    model: str,
) -> None:
    """生成压缩摘要并持久化（与同步路径 _generate_summary 同语义，无冷却状态）。

    Args:
        ctx: arq 任务上下文（job_id 等，未用）。
        conversation_id: 会话 ID（摘要持久化归属）。
        turns: 被压缩区 MemoryMessage.asdict() 列表（JSON 反序列化 dict 形态）。
        previous_summary: 上一代摘要正文（增量融合用），首轮为 None。
        compressed_count: 被压缩消息条数（持久化元数据）。
        compression_ratio: 压缩率（压缩后/压缩前，任务侧由压缩器预计算）。
        agent_id: Agent ID（模型配置解析）。
        user_id: 用户 ID（模型配置解析）。
        model: 对话主模型名（LLM 连接与 token 口径）。
    """
    from novamind.core.database.database import get_session_factory
    from novamind.engines.agent.memory.context_compressor import ContextCompressor
    from novamind.engines.agent.memory.interfaces import MemoryMessage
    from novamind.features.agent.services.host_memory_store import HostMemoryStorePort
    from novamind.features.user.services.model_config_service import ModelConfigService

    session = get_session_factory()()
    try:
        mcs = ModelConfigService(session)

        async def llm_factory():
            try:
                return await mcs.get_llm_client_by_model(user_id, model)
            except Exception:
                return await mcs.get_vlm_client_by_model(user_id, model)

        memory_messages = [MemoryMessage(**t) for t in turns]
        budget = _load_token_budget(model)
        store = HostMemoryStorePort(session)

        # 独立摘要 prompt 路径（与同步降级路径同构：序列化→脱敏→块转义→融合/首摘要）。
        # 对齐重放路径不移植：其价值在共享主请求前缀命中 KV cache，而异步任务
        # 与主请求已时序分离，重放无前缀可对齐。
        compressor = ContextCompressor(
            llm_client_factory=llm_factory,
            summary_store=store,
            conversation_id=conversation_id,
            agent_id=agent_id,
            user_id=user_id,
            model=model,
        )
        compressor._previous_summary = previous_summary
        content = compressor._serialize_turns(memory_messages)
        content = redact_sensitive_text(content)
        content = f"<conversation>\n{html.escape(content, quote=False)}\n</conversation>"

        if previous_summary:
            prompt = compressor._build_merge_prompt(
                previous_summary, content, token_budget=budget,
            )
        else:
            content = compressor._bound_text_head_tail(content, budget, 4000)
            prompt = compressor._build_summary_prompt(content)

        summary = await compressor._call_summary_llm(prompt=prompt, token_budget=budget)
        if not summary:
            logger.warning(
                "压缩摘要任务 LLM 生成失败",
                agent_id=agent_id, conversation_id=conversation_id,
            )
            return

        # 摘要尾部追加跨代资源清单段（与同步路径 merge 逻辑一致：
        # carried 从旧摘要解析 + 本代新提取，去重合并）
        carried = compressor._parse_carried_resources(previous_summary)
        new_lines = compressor._extract_resource_usages(memory_messages)
        merged = carried + [line for line in new_lines if line not in carried]
        if merged:
            summary = summary + compressor._resources_section(merged)

        summary_token_count = budget.count_text_tokens(summary)
        await store.save_summary(
            conversation_id=conversation_id,
            summary_text=summary,
            compressed_count=compressed_count,
            compression_ratio=compression_ratio,
            token_count=summary_token_count,
        )
        logger.info(
            "压缩摘要生成完成（异步）",
            agent_id=agent_id, conversation_id=conversation_id,
            compressed_count=compressed_count, ratio=round(compression_ratio, 2),
        )
    except Exception as e:
        logger.warning(
            "压缩摘要生成失败（异步）",
            agent_id=agent_id, conversation_id=conversation_id, error=str(e)[:200],
        )
    finally:
        await session.close()


def _load_token_budget(model: str):
    from novamind.engines.agent.memory.token_budget import TokenBudget

    return TokenBudget(model)
