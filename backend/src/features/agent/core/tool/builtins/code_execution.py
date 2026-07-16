"""
内置工具：代码执行

在 Docker 沙箱中执行代码，支持 Python、JavaScript、Shell
"""
import json
from typing import Any, Dict, List

from novamind.features.agent.core.tool.base import BaseTool
from novamind.core.middleware.structured_logging import get_logger

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
                        "Execute code in an isolated Docker sandbox and return the results. "
                        "Supports python, javascript, and shell.\n\n"
                        "WHEN TO USE:\n"
                        "- Data analysis, math calculations, or numerical computations\n"
                        "- Code verification, testing snippets, or debugging\n"
                        "- Text processing, data transformation, or format conversion\n"
                        "- Generating charts, tables, or structured output from data\n\n"
                        "CONSTRAINTS:\n"
                        "- Runs in an isolated container with NO network access\n"
                        "- Cannot access the host filesystem or external services\n"
                        "- Default timeout is 30 seconds (configurable)\n"
                        "- Output includes stdout, stderr, and exit_code\n\n"
                        "TIPS:\n"
                        "- For data analysis, include print() statements to see results\n"
                        "- For multi-step logic, write a complete script rather than snippets\n"
                        "- Handle errors gracefully in your code rather than relying on try/except in the caller"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "The code to execute",
                            },
                            "language": {
                                "type": "string",
                                "enum": ["python", "javascript", "shell"],
                                "description": "Programming language",
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Execution timeout in seconds (default 30)",
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
            "## Code Execution\n"
            "ALWAYS use code_execution for:\n"
            "- Calculations, math, numerical computations (never compute mentally)\n"
            "- Data analysis, text processing, format conversion\n"
            "- Verifying code correctness or testing snippets\n\n"
            "Rules:\n"
            "- Always include print() statements to see results\n"
            "- The sandbox has NO network access — never attempt API calls or web requests\n"
            "- Keep code focused and minimal — write only what's needed\n"
            "- If code fails, read the error, fix it, and retry — don't guess at fixes\n"
            "- For multi-step logic, write a complete script rather than fragments"
        )
