"""
记忆管理工具

参考 Hermes 的 memory tool，管理 MEMORY.md 和 USER.md。
支持 add / replace / remove 操作。
"""
import json
from typing import Any, Dict, List

from src.features.agent.core.tool.base import BaseTool


class ClawMateMemoryTool(BaseTool):
    """记忆管理工具"""

    @property
    def name(self) -> str:
        return "clawmate_memory"

    @property
    def description(self) -> str:
        return "管理持久化记忆笔记"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "clawmate_memory",
                    "description": (
                        "保存持久化信息到记忆文件，跨会话保留。记忆内容会注入到未来的对话中，因此请保持简洁、聚焦。\n\n"
                        "何时保存（主动保存，不要等用户要求）：\n"
                        "- 用户纠正你或说「记住这个」「别再这样做了」\n"
                        "- 用户分享了偏好、习惯或个人细节\n"
                        "- 你发现了关于环境的信息（OS、工具、项目结构）\n"
                        "- 你学到了特定于这个用户的约定、API 技巧或工作流\n\n"
                        "两个存储目标：\n"
                        "- 'memory': 你的笔记 — 环境事实、项目约定、工具技巧、学到的教训\n"
                        "- 'user': 用户信息 — 偏好、沟通风格、工作习惯\n\n"
                        "操作：add（添加）、replace（替换，用 old_content 匹配）、remove（删除，用 old_content 匹配）\n\n"
                        "不要保存：任务进度、会话结果、临时 TODO 状态。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["add", "replace", "remove"],
                                "description": "要执行的操作",
                            },
                            "store": {
                                "type": "string",
                                "enum": ["memory", "user"],
                                "description": "存储目标：'memory' 为个人笔记，'user' 为用户偏好",
                            },
                            "content": {
                                "type": "string",
                                "description": "条目内容。add 和 replace 操作必填。",
                            },
                            "old_content": {
                                "type": "string",
                                "description": "要匹配的旧内容子串。replace 和 remove 操作必填。",
                            },
                        },
                        "required": ["action", "store"],
                    },
                },
            }
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        memory_store = context.get("memory_store")
        if memory_store is None:
            return json.dumps({"success": False, "error": "记忆存储不可用"}, ensure_ascii=False)

        action = arguments.get("action", "")
        store = arguments.get("store", "memory")
        content = arguments.get("content")
        old_content = arguments.get("old_content")

        result = await memory_store.execute(
            action=action,
            store=store,
            content=content,
            old_content=old_content,
        )
        return result
