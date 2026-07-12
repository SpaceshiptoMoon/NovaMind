"""
ClawMate 上下文压缩适配器

将 ClawMate 的 Dict 格式消息转换为 MemoryMessage，
复用 NovaMind 已有的 ContextCompressor 五阶段压缩。

数据流：
  AgentEngine.run() → context overflow → compress_fn(messages)
    → dict_to_memory_message() → ContextCompressor.compress()
    → memory_message_to_dict() → 返回压缩后的 messages
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent.core.memory.interfaces import MemoryMessage

logger = get_logger(__name__)


def dict_to_memory_message(msg: Dict[str, Any]) -> MemoryMessage:
    """OpenAI Dict → MemoryMessage

    支持标准 OpenAI 消息格式：
    - {"role": "user/assistant/system/tool", "content": "..."}
    - {"role": "assistant", "content": null, "tool_calls": [...]}
    - {"role": "tool", "tool_call_id": "...", "content": "..."}
    """
    content = msg.get("content")
    # content 可能是 None（assistant 带 tool_calls 时）
    if content is None:
        content = ""

    return MemoryMessage(
        role=msg.get("role", "user"),
        content=content,
        tool_call_id=msg.get("tool_call_id"),
        tool_name=msg.get("name"),
        tool_calls=msg.get("tool_calls"),
        metadata=msg.get("metadata", {}),
    )


def memory_message_to_dict(msg: MemoryMessage) -> Dict[str, Any]:
    """MemoryMessage → OpenAI Dict"""
    d: Dict[str, Any] = {"role": msg.role}

    # content 处理
    if msg.content is not None:
        d["content"] = msg.content
    elif msg.tool_calls:
        d["content"] = None
    else:
        d["content"] = ""

    # tool_calls（assistant 消息）
    if msg.tool_calls:
        d["tool_calls"] = msg.tool_calls

    # tool 相关字段
    if msg.tool_call_id:
        d["tool_call_id"] = msg.tool_call_id
    if msg.tool_name:
        d["name"] = msg.tool_name

    return d


def create_compress_fn(
    llm_client: Any,
    context_length: int = 128000,
) -> Callable:
    """创建 compress_fn 回调供 AgentEngine.run() 使用

    Args:
        llm_client: BaseLLM 实例，用于 LLM 摘要生成
        context_length: 模型上下文窗口大小（tokens）

    Returns:
        async (messages: List[Dict]) -> List[Dict] 回调函数
    """
    from novamind.features.agent.core.memory.context_compressor import ContextCompressor
    from novamind.features.agent.core.memory.token_budget import TokenBudget

    def llm_factory():
        return llm_client

    compressor = ContextCompressor(
        llm_client_factory=llm_factory,
        summary_repository=None,       # ClawMate 不持久化到 DB
        long_term_memory=None,         # 不使用 agent 长期记忆
        todo_store=None,               # 后续集成
    )

    token_budget = TokenBudget(model_name="")
    threshold = int(context_length * 0.50)  # 50% 阈值触发压缩

    async def compress_fn(messages: List[Dict]) -> List[Dict]:
        """压缩回调：Dict → MemoryMessage → 压缩 → Dict"""
        try:
            # Dict → MemoryMessage
            mem_msgs = [dict_to_memory_message(m) for m in messages]

            # 执行五阶段压缩
            compressed, _, _ = await compressor.compress(
                messages=mem_msgs,
                available_tokens=threshold,
                token_budget=token_budget,
                conversation_id=None,
            )

            # MemoryMessage → Dict
            result = [memory_message_to_dict(m) for m in compressed]

            logger.info(
                "ClawMate 上下文压缩完成",
                original=len(messages),
                compressed=len(result),
            )

            return result

        except Exception as e:
            logger.error("ClawMate 上下文压缩失败，返回原始消息", error=str(e))
            return messages  # 压缩失败时返回原始消息，不中断对话

    return compress_fn
