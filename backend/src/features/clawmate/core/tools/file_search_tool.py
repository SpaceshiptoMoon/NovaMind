"""
文件搜索工具

支持按文件名搜索和按内容搜索两种模式。
"""
import json
from typing import Any, Dict, List

from src.features.agent.core.tool.base import BaseTool


class FileSearchTool(BaseTool):
    """文件搜索工具"""

    @property
    def name(self) -> str:
        return "file_search"

    @property
    def description(self) -> str:
        return "搜索文件名或文件内容"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_files",
                    "description": (
                        "搜索文件系统。支持两种模式：\n"
                        "- mode='name': 按文件名模式搜索（如 *.py, *.ts）\n"
                        "- mode='content': 按内容搜索（使用正则表达式）\n"
                        "两种模式都支持限制结果数量。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "搜索根目录",
                            },
                            "pattern": {
                                "type": "string",
                                "description": "搜索模式：文件名 glob 或正则表达式",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["name", "content"],
                                "description": "搜索模式：'name' 按文件名，'content' 按文件内容",
                                "default": "name",
                            },
                            "file_pattern": {
                                "type": "string",
                                "description": "内容搜索时过滤的文件类型（如 *.py）",
                                "default": "*",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "最大结果数",
                                "default": 30,
                            },
                        },
                        "required": ["path", "pattern"],
                    },
                },
            }
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        file_ops = context["file_ops"]
        mode = arguments.get("mode", "name")

        if mode == "content":
            result = await file_ops.grep(
                path=arguments.get("path", ""),
                pattern=arguments.get("pattern", ""),
                file_pattern=arguments.get("file_pattern", "*"),
                max_results=arguments.get("max_results", 30),
            )
        else:
            result = await file_ops.search_files(
                path=arguments.get("path", ""),
                pattern=arguments.get("pattern", "*"),
                max_results=arguments.get("max_results", 30),
            )

        return json.dumps(result, ensure_ascii=False)
