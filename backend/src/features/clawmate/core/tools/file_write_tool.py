"""
文件写入工具
"""
import json
from typing import Any, Dict, List

from novamind.features.agent.core.tool.base import BaseTool


class FileWriteTool(BaseTool):
    """文件写入工具"""

    @property
    def name(self) -> str:
        return "file_write"

    @property
    def description(self) -> str:
        return "写入或创建文件"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": (
                        "写入文件内容（覆盖写入）。如果文件不存在会自动创建。"
                        "设置 create_dirs=true 可以自动创建父目录。"
                        "建议先读取文件了解现有内容，避免意外覆盖。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "文件路径",
                            },
                            "content": {
                                "type": "string",
                                "description": "要写入的文件内容",
                            },
                            "create_dirs": {
                                "type": "boolean",
                                "description": "是否自动创建父目录",
                                "default": False,
                            },
                        },
                        "required": ["path", "content"],
                    },
                },
            }
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        file_ops = context["file_ops"]
        result = await file_ops.write_file(
            path=arguments.get("path", ""),
            content=arguments.get("content", ""),
            create_dirs=arguments.get("create_dirs", False),
        )
        return json.dumps(result, ensure_ascii=False)
