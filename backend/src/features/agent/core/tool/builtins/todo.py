"""
内置工具：任务管理

参照 Hermes TodoTool 设计。行为指导全部放在工具 schema description 中，
不注入 system prompt fragment。
"""
import json
from typing import Any, Dict, List

from novamind.features.agent.core.tool.base import BaseTool
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class TodoTool(BaseTool):
    """任务管理工具"""

    def __init__(self, todo_store):
        self._todo_store = todo_store

    @property
    def name(self) -> str:
        return "todo"

    @property
    def description(self) -> str:
        return "任务清单管理工具"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "todo",
                    "description": (
                        "Manage your task list for the current session. Use for complex tasks "
                        "with 3+ steps or when the user provides multiple tasks. "
                        "Call with no parameters to read the current list.\n\n"
                        "Writing:\n"
                        "- Provide 'items' array to create/update tasks\n"
                        "- merge=false (default): replace the entire list with a fresh plan\n"
                        "- merge=true: update existing items by id, add any new ones\n\n"
                        "Each item: {id: string, content: string, "
                        "status: pending|in_progress|completed|cancelled}\n"
                        "List order is priority. Only ONE item in_progress at a time.\n"
                        "Mark items completed immediately when done. If something fails, "
                        "cancel it and add a revised item.\n\n"
                        "When to use:\n"
                        "- User asks for a complex multi-step task\n"
                        "- You need to track which steps are done vs remaining\n"
                        "- User asks you to make a plan or checklist\n\n"
                        "When NOT to use:\n"
                        "- Simple single-turn questions\n"
                        "- Tasks that don't need progress tracking\n\n"
                        "Always returns the full current list."
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
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
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
        return ""
