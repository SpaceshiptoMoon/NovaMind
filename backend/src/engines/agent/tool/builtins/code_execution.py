"""
内置工具：代码执行

在 Docker 沙箱中执行代码，支持 Python、JavaScript、Shell
"""
import json
from typing import Any

from novamind.engines.agent.tool.base import BaseTool
from novamind.shared.logging import get_logger

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

    def get_tools(self) -> list[dict[str, Any]]:
        """返回 run_code 的 OpenAI function calling 定义（语言枚举与超时参数）。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "run_code",
                    "description": (
                        "Execute code in an isolated Docker sandbox and return stdout, "
                        "stderr, and exit_code. Supports python, javascript, and shell.\n\n"
                        "DEPENDS ON:\n"
                        "- Nothing upstream; the sandbox has NO network access and no "
                        "host filesystem — bundle any data the code needs into the "
                        "code itself.\n\n"
                        "WHEN TO USE:\n"
                        "- Math, data analysis, transformations where you must verify "
                        "a computed result rather than guess\n"
                        "- Testing/verifying snippets, format conversions, generating "
                        "structured output\n\n"
                        "NOT FOR:\n"
                        "- Fetching web resources (no network in sandbox)\n"
                        "- Searching user documents or the web (use knowledge_search / "
                        "web_search first, then compute on the returned data)\n\n"
                        "TIPS: include print() statements to see results; write one "
                        "complete script rather than fragments. Default timeout 30s "
                        "(configurable per call)."
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
        self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """路由 run_code 到沙箱执行，未知工具名返回错误 JSON。

        Args:
            tool_name: 工具名（仅认 run_code）。
            arguments: 工具参数（code/language/timeout）。
            context: 执行上下文（本工具不读取）。

        Returns:
            JSON 文本：成功为 stdout/stderr/exit_code 等执行摘要，参数缺失或失败为 {error}。
        """
        if tool_name == "run_code":
            return await self._run_code(arguments)
        return json.dumps({"error": f"未知工具：{tool_name}"}, ensure_ascii=False)

    async def _run_code(self, args: dict[str, Any]) -> str:
        """在受限沙箱执行代码片段，返回 stdout/stderr 摘要。"""
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
        """返回代码执行工具的使用纪律片段（何时必须用、沙箱无网络、失败重试策略）。"""
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
