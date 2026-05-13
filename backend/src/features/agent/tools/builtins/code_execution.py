"""
内置工具：代码执行

在 Docker 沙箱中执行代码，支持 Python、JavaScript、Shell
"""
import json
from typing import Any, Dict, List, Optional

from src.features.agent.tools.base import BaseTool
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class CodeExecutionTool(BaseTool):
    """代码执行工具"""

    def __init__(self, sandbox: Any):
        """
        初始化代码执行工具

        Args:
            sandbox: DockerSandbox 实例
        """
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "code_execution"

    @property
    def description(self) -> str:
        return "在隔离沙箱中执行代码，支持 Python、JavaScript、Shell"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "run_code",
                    "description": (
                        "在隔离的沙箱环境中执行代码并返回运行结果。"
                        "支持 python、javascript、shell 三种语言。"
                        "代码在 Docker 容器中运行，无法访问网络和外部文件系统。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "要执行的代码",
                            },
                            "language": {
                                "type": "string",
                                "enum": ["python", "javascript", "shell"],
                                "description": "编程语言",
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "执行超时时间（秒），默认 30",
                                "default": 30,
                            },
                        },
                        "required": ["code", "language"],
                    },
                },
            },
        ]

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        if tool_name == "run_code":
            return await self._run_code(arguments)
        return json.dumps({"error": f"未知工具：{tool_name}"}, ensure_ascii=False)

    async def _run_code(self, args: Dict[str, Any]) -> str:
        """执行代码"""
        code = args.get("code", "")
        language = args.get("language", "")
        timeout = args.get("timeout")

        if not code:
            return json.dumps({"error": "代码不能为空"}, ensure_ascii=False)
        if not language:
            return json.dumps({"error": "必须指定编程语言"}, ensure_ascii=False)

        try:
            result = await self._sandbox.execute(
                language=language,
                code=code,
                timeout=timeout,
            )

            return json.dumps(
                {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.exit_code,
                    "execution_time_ms": result.execution_time_ms,
                    "language": result.language,
                    "timed_out": result.timed_out,
                },
                ensure_ascii=False,
            )

        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                "代码执行失败",
                language=language,
                error=str(e),
                error_type=error_type,
            )
            return json.dumps(
                {
                    "error": str(e),
                    "error_type": error_type,
                    "language": language,
                },
                ensure_ascii=False,
            )

    def get_system_prompt_fragment(self) -> str:
        return (
            "你可以使用 run_code 工具在沙箱环境中执行代码。"
            "支持的语言：python、javascript、shell。"
            "当需要数据分析、数学计算、代码验证、文本处理时使用此工具。"
            "代码在隔离的 Docker 容器中运行，无法访问网络和外部文件系统。"
            "执行结果包含 stdout（标准输出）、stderr（标准错误）和 exit_code（退出码）。"
        )
