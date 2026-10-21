"""本地工作区内置工具：工作模式六件套（read/glob/grep/write/edit/bash）。

工具定义与 Claude Code / dsh 同名工具语义对齐；会话未绑定工作区时端口缺位，
execute_tool 返回引导文案（能力缺失优于报错栈）。绑定会话的 system prompt
fragment 由引擎经 context["workspace_prompt"] 动态注入（工作目录+守则）。
"""
import json
from typing import Any

from novamind.engines.agent.tool.base import BaseTool

_WORKSPACE_MISSING = (
    "当前会话未绑定本地工作区。请用户在会话设置中绑定工作区"
    "（选择设备与授权文件夹）后再使用本地工具。"
)


class LocalWorkspaceTool(BaseTool):
    """本地工作区工具（工作模式默认必带：三只读 + 两写入 + 命令执行）"""

    @property
    def name(self) -> str:
        return "local_workspace"

    @property
    def description(self) -> str:
        return "本地工作区工具：读写、检索用户授权文件夹内的文件并执行命令"

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
                        "- Reading a file before editing it (required: edit needs exact text)\n\n"
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
                    "name": "write",
                    "description": (
                        "Write a file in the workspace, replacing its ENTIRE content "
                        "(creates parent dirs). Use only for new files or full rewrites.\n\n"
                        "WHEN TO USE:\n"
                        "- Creating a new file\n"
                        "- Intentionally replacing a whole file you have read\n\n"
                        "NOT FOR:\n"
                        "- Changing part of an existing file (use edit — it only sends "
                        "the diff and cannot silently drop the rest of the file)"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "工作区内相对路径（父目录自动创建）"},
                            "content": {"type": "string", "description": "完整文件内容（覆写全文）"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "edit",
                    "description": (
                        "Exact string replacement in an existing file. old_string must "
                        "match uniquely unless replace_all=true. ALWAYS read the file "
                        "immediately before editing — edit fails if the text is not found.\n\n"
                        "WHEN TO USE:\n"
                        "- Modifying existing code/config with a minimal, surgical change\n"
                        "- Renaming a symbol across one file (replace_all=true)\n\n"
                        "NOT FOR:\n"
                        "- Creating new files (use write)\n"
                        "- Fuzzy or regex replacement (exact literal text only)"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "工作区内相对路径"},
                            "old_string": {"type": "string", "description": "要被替换的原文（须唯一，含足够上下文）"},
                            "new_string": {"type": "string", "description": "替换后的新文本"},
                            "replace_all": {"type": "boolean", "description": "全部命中处替换（缺省 false，仅替换唯一命中）"},
                        },
                        "required": ["path", "old_string", "new_string"],
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

    def get_system_prompt_fragment(self) -> str:
        """工作模式守则（enabled_tools 含 local_workspace 时注入）。

        工作目录路径不在此处——它随会话变化，经 context["workspace_prompt"]
        由 chat_service 追加（避免进入按 agent 冻结的 prompt 缓存）。
        """
        return (
            "# Workspace Mode\n"
            "You are working in the user's local workspace as a coding agent.\n"
            "- ALWAYS read a file immediately before editing it: edit matches exact "
            "text and fails on stale content.\n"
            "- Prefer read/glob/grep over shell commands (cat/ls/find/grep in bash) — "
            "they are faster, safer, and structured.\n"
            "- Prefer edit over write for existing files: write replaces the ENTIRE "
            "file and risks dropping content you have not seen.\n"
            "- Paths are workspace-relative; absolute paths and `..` are rejected.\n"
            "- Before destructive shell commands (delete/move), verify the target "
            "path is the intended one."
        )

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        port = context.get("local_workspace_port")
        if port is None:
            return json.dumps({"error": _WORKSPACE_MISSING}, ensure_ascii=False)
        result = await port.execute(tool_name, arguments)
        return json.dumps(result, ensure_ascii=False)
