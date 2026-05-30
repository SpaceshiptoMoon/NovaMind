"""
内置工具：读取截断的完整工具结果

当工具返回超大结果被截断时，LLM 可通过此工具按 tool_call_id
从 agent_tool_calls 表取回完整结果。
"""
import json
from typing import Any, Dict, List

from src.features.agent.core.tool.base import BaseTool
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class ReadToolResultTool(BaseTool):
    """读取被截断的完整工具结果"""

    @property
    def name(self) -> str:
        return "read_tool_result"

    @property
    def description(self) -> str:
        return "读取之前被截断的工具调用完整结果"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_tool_result",
                    "description": (
                        "Retrieve the full output of a previous tool call that was truncated. "
                        "Use this when you see a truncation notice referencing a tool_call_id. "
                        "Supports pagination via offset and limit parameters for very large results."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tool_call_id": {
                                "type": "integer",
                                "description": "截断提示中引用的 tool_call_id",
                            },
                            "offset": {
                                "type": "integer",
                                "description": "起始字符偏移量（默认 0）",
                                "default": 0,
                            },
                            "limit": {
                                "type": "integer",
                                "description": "最多返回的字符数（默认 10000）",
                                "default": 10000,
                            },
                        },
                        "required": ["tool_call_id"],
                    },
                },
            }
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        tc_id = arguments.get("tool_call_id")
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit", 10000)

        if tc_id is None:
            return json.dumps({"error": "缺少 tool_call_id 参数"})

        db = context.get("db_session")
        if not db:
            return json.dumps({"error": "无法访问数据库"})

        from sqlalchemy import select
        from src.features.agent.models.tool_call import AgentToolCall

        stmt = select(AgentToolCall).where(AgentToolCall.id == tc_id)
        result = await db.execute(stmt)
        tc = result.scalar_one_or_none()

        if not tc:
            return json.dumps({"error": f"未找到工具调用记录: {tc_id}"})

        content = tc.result or "(空结果)"
        total_length = len(content)

        if offset > 0 or limit < total_length:
            sliced = content[offset : offset + limit]
            return json.dumps(
                {
                    "content": sliced,
                    "offset": offset,
                    "limit": limit,
                    "total_length": total_length,
                    "has_more": offset + limit < total_length,
                },
                ensure_ascii=False,
            )

        return content

    def get_system_prompt_fragment(self) -> str:
        return ""
