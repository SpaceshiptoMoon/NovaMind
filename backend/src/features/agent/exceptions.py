"""
Agent 模块异常定义

异常类放在模块顶层，供 API 层、服务层、仓储层共同使用，
避免仓储层反向依赖 API 层（违反 DDD 分层原则）。
"""
from typing import ClassVar

from novamind.core.middleware.base_exception_handler import BaseAPIError


class AgentError(BaseAPIError):
    """Agent 模块基础异常"""

    def __init__(self, message: str, code: str = "AGENT_ERROR"):
        super().__init__(message=message, code=code)


class AgentNotFoundError(AgentError):
    """Agent 不存在"""
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("agent_id",)

    def __init__(self, agent_id: int):
        super().__init__(
            message=f"Agent {agent_id} 不存在",
            code="AGENT_NOT_FOUND",
        )
        self.agent_id = agent_id


class SessionNotFoundError(AgentError):
    """会话不存在"""
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("session_id",)

    def __init__(self, session_id: str):
        super().__init__(
            message=f"会话 {session_id} 不存在",
            code="SESSION_NOT_FOUND",
        )
        self.session_id = session_id


class GroupNotFoundError(AgentError):
    """群不存在或非属主"""
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("group_id",)

    def __init__(self, group_id: int):
        super().__init__(
            message=f"群 {group_id} 不存在",
            code="GROUP_NOT_FOUND",
        )
        self.group_id = group_id


class GroupRunConflictError(AgentError):
    """同群已有进行中的一响，拒绝并发触发"""
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("group_id",)

    def __init__(self, group_id: int):
        super().__init__(
            message=f"群 {group_id} 正在讨论中，请等待当前一轮结束后再发送",
            code="GROUP_RUN_CONFLICT",
        )
        self.group_id = group_id


class McpServerError(AgentError):
    """MCP 服务器异常"""

    def __init__(self, message: str, code: str = "MCP_SERVER_ERROR"):
        super().__init__(message=message, code=code)


class McpServerNotFoundError(McpServerError):
    """MCP 服务器不存在"""
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("server_id",)

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
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("timeout", "language")

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
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("language", "supported")

    def __init__(self, language: str, supported: list[str]):
        super().__init__(
            message=f"不支持的语言 '{language}'，支持的语言: {', '.join(supported)}",
            code="SANDBOX_UNSUPPORTED_LANGUAGE",
        )
        self.language = language
        self.supported = supported


class ToolExecutionError(AgentError):
    """工具执行异常"""
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("tool_name",)

    def __init__(self, tool_name: str, message: str):
        super().__init__(
            message=f"工具 {tool_name} 执行失败：{message}",
            code="TOOL_EXECUTION_ERROR",
        )
        self.tool_name = tool_name


class ToolNotFoundError(AgentError):
    """工具不存在"""
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("tool_name",)

    def __init__(self, tool_name: str):
        super().__init__(
            message=f"工具 {tool_name} 不存在",
            code="TOOL_NOT_FOUND",
        )
        self.tool_name = tool_name


class AgentMaxIterationsError(AgentError):
    """达到最大迭代次数"""
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("max_iterations",)

    def __init__(self, max_iterations: int):
        super().__init__(
            message=f"已达到最大迭代次数 {max_iterations}",
            code="AGENT_MAX_ITERATIONS",
        )
        self.max_iterations = max_iterations


class MemoryNotFoundError(AgentError):
    """记忆不存在"""
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("memory_id",)

    def __init__(self, memory_id: int):
        super().__init__(
            message=f"记忆 {memory_id} 不存在",
            code="MEMORY_NOT_FOUND",
        )
        self.memory_id = memory_id


class AttachmentNotFoundError(AgentError):
    """聊天附件不存在"""
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("attachment_id",)

    def __init__(self, attachment_id: int):
        super().__init__(
            message=f"附件 {attachment_id} 不存在",
            code="ATTACHMENT_NOT_FOUND",
        )
        self.attachment_id = attachment_id


class AttachmentUploadError(AgentError):
    """附件上传/读取失败（服务未初始化、类型不支持、超限、内容不匹配）"""

    def __init__(self, message: str):
        super().__init__(f"附件处理失败: {message}", "ATTACHMENT_ERROR")


class RunnerDeviceError(AgentError):
    """伴生 runner 设备异常基类"""

    def __init__(self, message: str, code: str = "RUNNER_DEVICE_ERROR"):
        super().__init__(message=message, code=code)


class RunnerDeviceNotFoundError(RunnerDeviceError):
    """设备不存在或不属于当前用户"""
    _serializable_attrs: ClassVar[tuple[str, ...]] = ("device_id",)

    def __init__(self, device_id: int):
        super().__init__(
            message=f"设备 {device_id} 不存在",
            code="RUNNER_DEVICE_NOT_FOUND",
        )
        self.device_id = device_id


class RunnerPairingError(RunnerDeviceError):
    """配对失败（token 无效/过期/已用）"""

    def __init__(self, message: str = "配对凭证无效或已过期"):
        super().__init__(message, "RUNNER_PAIRING_ERROR")
