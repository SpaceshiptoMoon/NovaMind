"""
Agent 模块异常定义
"""
from typing import List


class AgentError(Exception):
    """Agent 模块基础异常"""

    def __init__(self, message: str, code: str = "AGENT_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class AgentNotFoundError(AgentError):
    """Agent 不存在"""

    def __init__(self, agent_id: int):
        super().__init__(
            message=f"Agent {agent_id} 不存在",
            code="AGENT_NOT_FOUND",
        )
        self.agent_id = agent_id


class SessionNotFoundError(AgentError):
    """会话不存在"""

    def __init__(self, session_id: str):
        super().__init__(
            message=f"会话 {session_id} 不存在",
            code="SESSION_NOT_FOUND",
        )
        self.session_id = session_id


class McpServerError(AgentError):
    """MCP 服务器异常"""

    def __init__(self, message: str, code: str = "MCP_SERVER_ERROR"):
        super().__init__(message=message, code=code)


class McpServerNotFoundError(McpServerError):
    """MCP 服务器不存在"""

    def __init__(self, server_id: int):
        super().__init__(
            message=f"MCP 服务器 {server_id} 不存在",
            code="MCP_SERVER_NOT_FOUND",
        )
        self.server_id = server_id


class McpConnectionError(McpServerError):
    """MCP 连接异常"""

    def __init__(self, message: str):
        super().__init__(message=message, code="MCP_CONNECTION_ERROR")


class SandboxError(AgentError):
    """沙箱异常基类"""

    def __init__(self, message: str, code: str = "SANDBOX_ERROR"):
        super().__init__(message=message, code=code)


class SandboxNotAvailableError(SandboxError):
    """沙箱不可用（Docker 未启动或未安装）"""

    def __init__(self):
        super().__init__(
            message="代码执行沙箱不可用，请确保 Docker 已安装并启动",
            code="SANDBOX_NOT_AVAILABLE",
        )


class SandboxTimeoutError(SandboxError):
    """代码执行超时"""

    def __init__(self, timeout: int, language: str):
        super().__init__(
            message=f"{language} 代码执行超时（{timeout}秒）",
            code="SANDBOX_TIMEOUT",
        )
        self.timeout = timeout
        self.language = language


class SandboxExecutionError(SandboxError):
    """代码执行异常"""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="SANDBOX_EXECUTION_ERROR",
        )


class UnsupportedLanguageError(SandboxError):
    """不支持的语言"""

    def __init__(self, language: str, supported: List[str]):
        super().__init__(
            message=f"不支持的语言 '{language}'，支持的语言: {', '.join(supported)}",
            code="SANDBOX_UNSUPPORTED_LANGUAGE",
        )
        self.language = language
        self.supported = supported


class ToolExecutionError(AgentError):
    """工具执行异常"""

    def __init__(self, tool_name: str, message: str):
        super().__init__(
            message=f"工具 {tool_name} 执行失败：{message}",
            code="TOOL_EXECUTION_ERROR",
        )
        self.tool_name = tool_name


class ToolNotFoundError(AgentError):
    """工具不存在"""

    def __init__(self, tool_name: str):
        super().__init__(
            message=f"工具 {tool_name} 不存在",
            code="TOOL_NOT_FOUND",
        )
        self.tool_name = tool_name


class AgentMaxIterationsError(AgentError):
    """达到最大迭代次数"""

    def __init__(self, max_iterations: int):
        super().__init__(
            message=f"已达到最大迭代次数 {max_iterations}",
            code="AGENT_MAX_ITERATIONS",
        )
        self.max_iterations = max_iterations
