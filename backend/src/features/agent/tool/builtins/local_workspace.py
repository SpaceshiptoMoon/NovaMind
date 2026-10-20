"""本地工作区内置工具：read/glob/grep（P0）——经 LocalWorkspacePort 执行。

工具定义与 Claude Code 同名工具语义对齐；会话未绑定工作区时端口缺位，
execute_tool 返回引导文案（能力缺失优于报错栈）。
"""
import json
from typing import Any

from novamind.engines.agent.tool.base import BaseTool

_WORKSPACE_MISSING = (
    "当前会话未绑定本地工作区。请用户在会话设置中绑定工作区"
    "（选择设备与授权文件夹）后再使用本地工具。"
)


class LocalWorkspaceTool(BaseTool):
    """本地工作区只读工具（read/glob/grep；write/edit/bash 属 P1/P2）"""

    @property
    def name(self) -> str:
        return "local_workspace"

    @property
    def description(self) -> str:
        return "本地工作区工具：读取与检索用户授权文件夹内的文件"

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": (
                        "Read a text file from the user's local workspace. Returns numbered "
                        "lines; use offset/limit to page through large files.\n\n"
                        "WHEN TO USE:\n"
                        "- Inspecting source files, configs, or docs inside the workspace\n"
                        "- Reading a file found earlier via glob/grep\n\n"
                        "NOT FOR:\n"
                        "- Files outside the workspace root (rejected by security check)\n"
                        "- Searching by content (use grep) or by name pattern (use glob)"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "工作区内相对路径"},
                            "offset": {"type": "integer", "description": "起始行号（1 起，缺省 1）"},
                            "limit": {"type": "integer", "description": "读取行数（缺省 2000）"},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "glob",
                    "description": (
                        "List files in the workspace matching a glob pattern (e.g. '**/*.py'). "
                        "Results sorted by modification time, newest first.\n\n"
                        "WHEN TO USE:\n"
                        "- Discovering files by name/extension before reading them\n"
                        "- Surveying project layout (e.g. 'src/**/*.ts')\n\n"
                        "NOT FOR:\n"
                        "- Finding files by content (use grep)\n"
                        "- Reading file contents (use read)"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "glob 模式"},
                            "path": {"type": "string", "description": "检索起始目录（相对根，缺省根）"},
                        },
                        "required": ["pattern"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "grep",
                    "description": (
                        "Search file contents with a regular expression (ripgrep semantics) "
                        "across the workspace. Set output_mode='files_with_matches' to list "
                        "matching files only.\n\n"
                        "WHEN TO USE:\n"
                        "- Locating definitions, usages, or config values by content\n"
                        "- Narrowing to specific file types with the glob filter\n\n"
                        "NOT FOR:\n"
                        "- Listing files by name pattern (use glob)\n"
                        "- Dumping a whole file (use read)"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "正则表达式"},
                            "path": {"type": "string", "description": "检索起始目录（相对根，缺省根）"},
                            "glob": {"type": "string", "description": "文件名过滤（如 '*.py'）"},
                            "output_mode": {
                                "type": "string",
                                "enum": ["content", "files_with_matches"],
                                "description": "输出模式（缺省 content）",
                            },
                        },
                        "required": ["pattern"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": (
                        "Run a shell command in the workspace root (each call spawns a fresh "
                        "process; cwd is the workspace root, cd does NOT persist between calls). "
                        "Windows uses cmd, POSIX uses sh. Output truncated at 30k chars; "
                        "120s timeout kills the process.\n\n"
                        "WHEN TO USE:\n"
                        "- Running builds, tests, git, or project scripts\n"
                        "- Anything beyond read/glob/grep (env inspection, file transforms)\n\n"
                        "NOT FOR:\n"
                        "- Reading a known file (use read — cheaper and safer)\n"
                        "- Commands expecting interactivity (none available; use flags like -y)"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "要执行的命令（在工作区根运行）"},
                        },
                        "required": ["command"],
                    },
                },
            },
        ]

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        port = context.get("local_workspace_port")
        if port is None:
            return json.dumps({"error": _WORKSPACE_MISSING}, ensure_ascii=False)
        result = await port.execute(tool_name, arguments)
        return json.dumps(result, ensure_ascii=False)
