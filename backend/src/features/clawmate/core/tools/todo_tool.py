"""
ClawMate Todo 任务追踪工具

参考 Hermes TodoTool 设计，让 AI 在多步骤任务中追踪进度。
所有行为指导放在 schema description 中，不需要修改系统提示词。
"""

import json
from typing import Any, Dict, List, Optional

from src.features.agent.core.tool.base import BaseTool
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

VALID_STATUSES = frozenset({"pending", "in_progress", "completed", "cancelled"})


class ClawMateTodoStore:
    """内存版 TodoStore — 无 DB 依赖

    每个 ClawMateSessionState 持有一个实例。
    """

    def __init__(self):
        self._items: List[Dict[str, str]] = []

    def read(self) -> List[Dict[str, str]]:
        """读取当前任务列表（返回副本）"""
        return list(self._items)

    def write(self, todos: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """替换整个任务列表

        Args:
            todos: 新的任务列表，每项包含 id/content/status

        Returns:
            验证后的任务列表
        """
        validated = []
        for t in todos:
            status = t.get("status", "pending")
            if status not in VALID_STATUSES:
                status = "pending"
            validated.append({
                "id": str(t.get("id", "?")),
                "content": str(t.get("content", "(无描述)")),
                "status": status,
            })
        self._items = validated
        return list(self._items)

    def summary(self) -> Dict[str, int]:
        """统计各状态数量"""
        counts = {"total": 0, "pending": 0, "in_progress": 0, "completed": 0, "cancelled": 0}
        for item in self._items:
            counts["total"] += 1
            status = item["status"]
            if status in counts:
                counts[status] += 1
        return counts

    def format_active(self) -> str:
        """格式化活跃任务（用于上下文压缩后恢复）

        Returns:
            格式化的活跃任务字符串，无活跃任务时返回空字符串
        """
        active = [t for t in self._items if t["status"] in ("pending", "in_progress")]
        if not active:
            return ""

        markers = {
            "pending": "[ ]",
            "in_progress": "[>]",
        }
        lines = ["[活跃任务（上下文压缩后恢复）]"]
        for t in active:
            marker = markers.get(t["status"], "[?]")
            lines.append(f"- {marker} {t['id']}. {t['content']}")

        return "\n".join(lines)

    @property
    def has_active_items(self) -> bool:
        """是否有活跃任务"""
        return any(t["status"] in ("pending", "in_progress") for t in self._items)


class ClawMateTodoTool(BaseTool):
    """Todo 任务追踪工具"""

    @property
    def name(self) -> str:
        return "clawmate_todo"

    @property
    def description(self) -> str:
        return "管理当前会话的任务列表"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "clawmate_todo",
                    "description": (
                        "管理当前会话的任务列表。用于 3 步以上的复杂任务或多任务场景。\n\n"
                        "使用方式：\n"
                        "- 不传 todos 参数 → 读取当前列表\n"
                        "- 传 todos 参数 → 替换整个列表（创建新计划）\n\n"
                        "每个条目: {id: string, content: string, status: pending|in_progress|completed|cancelled}\n"
                        "列表顺序即优先级。同时只保持一个 in_progress。\n"
                        "完成时立即标记 completed。失败则 cancel 并添加修正条目。\n\n"
                        "何时使用：\n"
                        "- 用户要求完成多个步骤\n"
                        "- 复杂任务需要分解（如「搭建项目」→ 创建目录、初始化 git、写 README）\n"
                        "- 用户明确要求列计划\n\n"
                        "不要在简单单步操作时使用。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "todos": {
                                "type": "array",
                                "description": "任务列表。不传则读取当前列表。",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {
                                            "type": "string",
                                            "description": "任务标识（简短唯一字符串，如 '1'、'setup'）",
                                        },
                                        "content": {
                                            "type": "string",
                                            "description": "任务描述（清晰说明要做什么）",
                                        },
                                        "status": {
                                            "type": "string",
                                            "enum": ["pending", "in_progress", "completed", "cancelled"],
                                            "description": "任务状态",
                                        },
                                    },
                                    "required": ["id", "content", "status"],
                                },
                            },
                        },
                    },
                },
            }
        ]

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """执行 Todo 操作"""
        todo_store = context.get("todo_store")
        if todo_store is None:
            return json.dumps(
                {"error": "Todo 不可用"}, ensure_ascii=False
            )

        todos = arguments.get("todos")

        if todos is None:
            # 读取模式
            items = todo_store.read()
            return json.dumps(
                {"todos": items, "summary": todo_store.summary()},
                ensure_ascii=False,
            )

        # 写入模式
        if not isinstance(todos, list):
            return json.dumps(
                {"error": "todos 必须是数组"}, ensure_ascii=False
            )

        result = todo_store.write(todos)
        return json.dumps(
            {"todos": result, "summary": todo_store.summary()},
            ensure_ascii=False,
        )
