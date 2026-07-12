"""
目录列表工具
"""
import json
from typing import Any, Dict, List

from novamind.features.agent.core.tool.base import BaseTool


class ListDirectoryTool(BaseTool):
    """目录列表工具"""

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def description(self) -> str:
        return "列出目录内容"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": (
                        "列出指定目录下的文件和子目录。"
                        "默认不显示隐藏文件（以 . 开头的文件）。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "目录路径，默认为当前工作目录",
                                "default": ".",
                            },
                            "show_hidden": {
                                "type": "boolean",
                                "description": "是否显示隐藏文件",
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
        file_ops = context["file_ops"]
        result = await file_ops.list_dir(
            path=arguments.get("path", "."),
            show_hidden=arguments.get("show_hidden", False),
        )
        return json.dumps(result, ensure_ascii=False)
