"""
旧版对话记忆管理（兼容层）

后续会被 ShortTermMemory 替代，目前仍被 engine.py 使用。
"""
from typing import Any, Dict, List, Optional

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class ConversationMemory:
    """Agent 对话记忆管理器"""

    def __init__(self, max_context_tokens: int = 20000):
        self.max_context_tokens = max_context_tokens

    def build_messages(
        self,
        system_prompt: str,
        db_messages: List[Any],
        db_tool_calls: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        从数据库消息构建 OpenAI 格式的 messages 列表

        Args:
            system_prompt: 系统提示词
            db_messages: AgentMessage 列表（按 created_at 排序）
            db_tool_calls: AgentToolCall 列表

        Returns:
            OpenAI 格式的消息列表
        """
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]

        # 构建工具调用查找表：message_id -> tool_calls
        tool_calls_map: Dict[int, List[Any]] = {}
        if db_tool_calls:
            for tc in db_tool_calls:
                tool_calls_map.setdefault(tc.message_id, []).append(tc)

        # 从 tool 角色消息中提取原始 LLM call_id，按 tool_name 分组顺序消费
        # 确保 assistant tool_calls[].id 与 tool 消息 tool_call_id 一致
        tool_call_ids_by_name: Dict[str, List[str]] = {}
        for msg in db_messages:
            if msg.role == "tool" and msg.tool_call_id:
                tool_call_ids_by_name.setdefault(msg.tool_name or "", []).append(
                    msg.tool_call_id
                )

        for msg in db_messages:
            if msg.role == "user":
                messages.append({"role": "user", "content": msg.content or ""})

            elif msg.role == "assistant":
                msg_tool_calls = tool_calls_map.get(msg.id, [])

                if msg_tool_calls:
                    openai_tool_calls = []
                    for tc in msg_tool_calls:
                        # 从 tool 结果消息的消费队列中获取原始 LLM call_id
                        name_queue = tool_call_ids_by_name.get(tc.tool_name, [])
                        call_id = name_queue.pop(0) if name_queue else f"call_{tc.id}"

                        openai_tool_calls.append(
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": tc.tool_name,
                                    "arguments": tc.arguments
                                    if isinstance(tc.arguments, str)
                                    else str(tc.arguments),
                                },
                            }
                        )
                    messages.append(
                        {
                            "role": "assistant",
                            "content": msg.content,
                            "tool_calls": openai_tool_calls,
                        }
                    )
                else:
                    messages.append(
                        {"role": "assistant", "content": msg.content or ""}
                    )

            elif msg.role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id or "",
                        "content": msg.content or "",
                    }
                )

        return messages

    def should_compress(self, messages: List[Dict], token_count: int) -> bool:
        """判断是否需要压缩上下文"""
        return token_count > self.max_context_tokens

    def build_compressed_messages(
        self,
        system_prompt: str,
        summary: str,
        recent_messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        构建压缩后的消息列表

        Args:
            system_prompt: 系统提示词
            summary: 旧消息的摘要
            recent_messages: 保留的最近消息

        Returns:
            压缩后的消息列表
        """
        messages = [{"role": "system", "content": system_prompt}]

        if summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"以下是之前对话的摘要：\n{summary}",
                }
            )

        messages.extend(recent_messages)
        return messages
