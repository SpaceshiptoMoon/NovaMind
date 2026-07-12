"""
文件读取工具
"""
import json
from typing import Any, Dict, List

from novamind.features.agent.core.tool.base import BaseTool


class FileReadTool(BaseTool):
    """文件读取工具"""

    @property
    def name(self) -> str:
        return "file_read"

    @property
    def description(self) -> str:
        return "读取文件内容，支持分页"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": (
                        "读取指定文件的内容。支持分页读取大文件。"
                        "自动添加行号。二进制文件会被拒绝。"
                        "建议先读取文件开头了解结构，再按需读取特定部分。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "文件路径（支持相对路径和绝对路径）",
                            },
                            "offset": {
                                "type": "integer",
                                "description": "起始行号（0-based），默认 0",
                                "default": 0,
                            },
                            "limit": {
                                "type": "integer",
                                "description": "最大读取行数，默认 500",
                                "default": 500,
                            },
                        },
                        "required": ["path"],
                    },
                },
            }
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        file_ops = context["file_ops"]
        result = await file_ops.read_file(
            path=arguments.get("path", ""),
            offset=arguments.get("offset", 0),
            limit=arguments.get("limit", 500),
        )
        return json.dumps(result, ensure_ascii=False)
