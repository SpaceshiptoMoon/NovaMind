"""
内置工具：任务管理

参照 Hermes TodoTool 设计。行为指导全部放在工具 schema description 中，
不注入 system prompt fragment。
"""
import json
from typing import Any

from novamind.engines.agent.tool.base import BaseTool
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class TodoTool(BaseTool):
    """任务管理工具"""

    def __init__(self, todo_store):
        """注入任务存储（TodoStore），读写均绑定该存储实例。"""
        self._todo_store = todo_store

    @property
    def name(self) -> str:
        return "todo"

    @property
    def description(self) -> str:
        return "任务清单管理工具"

    def get_tools(self) -> list[dict[str, Any]]:
        """返回 todo 工具定义（items 写入与 merge 合并模式；无参数调用为读模式）。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "todo",
                    "description": (
                        "Maintain a visible task checklist for THIS session so the user "
                        "can follow progress.\n\n"
                        "DEPENDS ON:\n"
                        "- Nothing; call with no parameters to read the current list.\n\n"
                        "WHEN TO USE:\n"
                        "- Complex tasks with 3+ steps or multiple user requests at once\n"
                        "- Long executions where tracking done/remaining matters\n\n"
                        "NOT FOR:\n"
                        "- Single-step or trivial tasks (overhead without value)\n"
                        "- Durable facts across sessions (use memory)\n"
                        "- Delegating work to sub-agents (use task)\n\n"
                        "Writing: provide 'items' array — each item is {id: string, "
                        "content: string, status: pending|in_progress|completed|"
                        "cancelled}. merge=false (default) replaces the whole list; "
                        "merge=true updates by id and appends new ones.\n"
                        "List order is priority; only ONE item in_progress at a time; "
                        "mark completed immediately; on failure cancel and add a "
                        "revised item. Always returns the full current list."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "items": {
                                "type": "array",
                                "description": "Task items to write. Omit to read current list.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {
                                            "type": "string",
                                            "description": "Unique item identifier",
                                        },
                                        "content": {
                                            "type": "string",
                                            "description": "Task description",
                                        },
                                        "status": {
                                            "type": "string",
                                            "enum": ["pending", "in_progress", "completed", "cancelled"],
                                            "description": "Current status",
                                        },
                                    },
                                    "required": ["id", "content", "status"],
                                },
                            },
                            "merge": {
                                "type": "boolean",
                                "description": (
                                    "true: update existing items by id, add new ones. "
                                    "false (default): replace the entire list."
                                ),
                                "default": False,
                            },
                        },
                        "required": [],
                    },
                },
            }
        ]

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """按会话 ID 读或写任务清单：无 items 时读当前列表，有 items 时按 merge 写入并返回统计。

        Args:
            tool_name: 工具名（仅认 todo）。
            arguments: 工具参数：items 与 merge；无 items 即读模式。
            context: 执行上下文：conversation_id。

        Returns:
            JSON 文本：读模式为 items/total/active 统计；写模式为更新消息 + 同组统计。
        """
        conversation_id = context.get("conversation_id")

        if not conversation_id:
            return json.dumps({"error": "无法确定会话 ID"}, ensure_ascii=False)

        # Read mode: no items provided
        items = arguments.get("items")
        if not items:
            result = self._todo_store.read(conversation_id)
            return json.dumps({
                "items": result,
                "total": len(result),
                "active": sum(1 for t in result if t["status"] in ("pending", "in_progress")),
            }, ensure_ascii=False)

        # Write mode
        merge = arguments.get("merge", False)
        result = self._todo_store.write(conversation_id, items, merge=merge)
        active = [t for t in result if t["status"] in ("pending", "in_progress")]

        return json.dumps({
            "message": f"任务清单已更新，共 {len(result)} 项，{len(active)} 项待处理",
            "items": result,
            "total": len(result),
            "active": len(active),
        }, ensure_ascii=False)

    def get_system_prompt_fragment(self) -> str:
        # Hermes 设计：行为指导全部放在 schema description 中
        """故意返回空串：行为指导全部放在工具 schema description 中（Hermes 设计）。"""
        return ""
