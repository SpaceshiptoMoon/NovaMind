"""
流式响应处理器

将 AgentLLM 的 StreamChunk 转换为前端可消费的 SSE 事件，
同时负责中间状态的持久化（工具调用记录等）。
"""
import json
from typing import Any, Dict, List, Optional

from src.features.agent.core.llm.agent_llm import StreamChunk, CollectedToolCall
from src.features.agent.repository.agent_repository import (
    MessageRepository,
    ToolCallRepository,
)
from src.features.agent.models.message import AgentMessage
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class StreamEventHandler:
    """
    流式响应 → SSE 事件转换器

    核心职责：
    1. 将 StreamChunk 转换为 SSE 格式字符串
    2. 管理 content 缓冲区（拼接收到的文本片段）
    3. 管理工具调用记录的创建和更新
    4. 追踪 token 使用量
    """

    def __init__(
        self,
        conversation_id: int,
    ):
        self._conv_id = conversation_id
        self._content_buffer = ""
        self._total_tokens = 0
        self._tool_call_records: Dict[str, int] = {}  # call_id -> tc_db_id

    async def handle_chunk(
        self,
        chunk: StreamChunk,
        user_msg: AgentMessage,
        tc_repo: ToolCallRepository,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """
        处理一个流式块，返回 SSE 格式字符串

        Args:
            chunk: AgentLLM 产出的流式块
            user_msg: 触发本轮对话的用户消息
            tc_repo: 工具调用仓储（用于创建/更新记录）
            context: 执行上下文

        Returns:
            SSE 格式字符串，或 None（如 tool_call_end 由引擎层处理）
        """
        if chunk.type == "content":
            self._content_buffer += chunk.content
            return self._format_sse("content", {"content": chunk.content})

        elif chunk.type == "tool_call_start":
            tc = await tc_repo.create(
                message_id=user_msg.id,
                conversation_id=self._conv_id,
                tool_name=chunk.tool_name or "",
                tool_source="mcp" if (chunk.tool_name or "").startswith("mcp__") else "builtin",
                arguments={},
                status="running",
            )
            self._tool_call_records[chunk.tool_call_id or ""] = tc.id
            return self._format_sse("tool_call", {
                "tool_name": chunk.tool_name,
                "call_id": chunk.tool_call_id,
                "status": "running",
            })

        elif chunk.type == "tool_call_args":
            return self._format_sse("tool_call_args", {
                "call_id": chunk.tool_call_id,
                "delta": chunk.tool_arguments_delta,
            })

        elif chunk.type == "tool_call_end":
            return None  # 由引擎层处理工具执行后发送 tool_result

        elif chunk.type == "done":
            self._total_tokens = chunk.usage.get("total_tokens", 0) if chunk.usage else 0
            return None  # 由引擎层处理完成事件

        return None

    def get_full_content(self) -> str:
        """获取拼接后的完整文本"""
        return self._content_buffer

    def get_total_tokens(self) -> int:
        """获取总 token 使用量"""
        return self._total_tokens

    def get_tool_call_db_id(self, call_id: str) -> Optional[int]:
        """根据 call_id 获取工具调用记录的数据库 ID"""
        return self._tool_call_records.get(call_id)

    @staticmethod
    def _format_sse(event_type: str, data: dict) -> str:
        """格式化 SSE 事件"""
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
