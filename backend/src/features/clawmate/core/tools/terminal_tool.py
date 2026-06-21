"""
终端执行工具

将 LocalEnvironment.execute() 封装为 LLM 可调用的工具。
集成命令安全检测（两级防护）和输出处理（ANSI剥离 + 脱敏 + 头尾截断 + 退出码语义）。
"""

import asyncio
import json
from typing import Any, Dict, List

from src.features.agent.core.tool.base import BaseTool
from src.features.clawmate.core.command_safety import check_command_safety, interpret_exit_code
from src.shared.utils.ansi_strip import strip_ansi
from src.shared.utils.redact import redact_sensitive_text
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class TerminalTool(BaseTool):
    """Shell 命令执行工具"""

    @property
    def name(self) -> str:
        return "terminal"

    @property
    def description(self) -> str:
        return "在用户的终端环境中执行 Shell 命令"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "terminal",
                    "description": (
                        "在用户的本地终端环境中执行 Shell 命令。"
                        "支持所有标准 Shell 命令（ls, cat, grep, find, python, npm 等）。"
                        "命令在用户的工作目录中执行，环境变量和别名会跨命令保持。"
                        "对于长时间运行的命令，建议设置合理的 timeout。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "要执行的 Shell 命令",
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "超时时间（秒），默认 30",
                                "default": 30,
                            },
                        },
                        "required": ["command"],
                    },
                },
            }
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """执行终端命令"""
        env = context["env"]
        command = arguments.get("command", "")
        timeout = arguments.get("timeout", 30)

        if not command.strip():
            return json.dumps({"error": "命令不能为空"}, ensure_ascii=False)

        # 命令安全检测（两级防护）
        safe, reason = check_command_safety(command)
        if not safe:
            return json.dumps({"error": reason}, ensure_ascii=False)

        # 同步执行包装为异步
        result = await asyncio.to_thread(env.execute, command, timeout)

        # 输出处理流水线
        output = result["output"]
        output = self._process_output(output)

        # 截断（头尾分割，保留两端信息）
        config = self._load_config()
        max_size = config.get("max_output_size", 65536)
        truncated = False
        if len(output) > max_size:
            head = int(max_size * 0.4)
            tail = max_size - head
            omitted = len(output) - max_size
            output = (
                output[:head]
                + f"\n\n... [输出截断 - 省略 {omitted} 字符] ...\n\n"
                + output[-tail:]
            )
            truncated = True

        # 退出码语义解释
        exit_meaning = ""
        if result["returncode"] != 0:
            exit_meaning = interpret_exit_code(command, result["returncode"])

        response = {
            "output": output,
            "returncode": result["returncode"],
            "cwd": result["cwd"],
            "truncated": truncated,
        }
        if exit_meaning:
            response["exit_meaning"] = exit_meaning

        return json.dumps(response, ensure_ascii=False)

    @staticmethod
    def _process_output(output: str) -> str:
        """输出处理流水线：ANSI 剥离 → 敏感信息脱敏"""
        # 1. 剥离 ANSI 转义序列
        output = strip_ansi(output)
        # 2. 敏感信息脱敏
        output = redact_sensitive_text(output)
        return output

    @staticmethod
    def _load_config() -> dict:
        """加载 ClawMate 配置"""
        from src.features.clawmate.core.config import ClawMateConfig
        config = ClawMateConfig.from_yaml()
        return {
            "max_output_size": config.max_output_size,
        }
