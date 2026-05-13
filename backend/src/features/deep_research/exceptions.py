"""
深度研究模块异常定义

异常类放在模块顶层，供 API 层、服务层、仓储层共同使用，
避免仓储层反向依赖 API 层（违反 DDD 分层原则）。
"""

from typing import ClassVar, List

from src.core.middleware.base_exception_handler import BaseAPIError


class DeepResearchError(BaseAPIError):
    """深度研究模块基础异常"""

    def __init__(self, message: str, code: str = "DEEP_RESEARCH_ERROR"):
        super().__init__(message=message, code=code)


class ResearchNotFoundError(DeepResearchError):
    """研究会话不存在"""
    _serializable_attrs: ClassVar[List[str]] = ["session_id"]

    def __init__(self, session_id: str):
        super().__init__(
            message=f"研究会话 {session_id} 不存在",
            code="RESEARCH_NOT_FOUND",
        )
        self.session_id = session_id


class ResearchFailedError(DeepResearchError):
    """研究执行失败"""
    _serializable_attrs: ClassVar[List[str]] = ["session_id", "error_message"]

    def __init__(self, session_id: str, error_message: str):
        super().__init__(
            message=f"研究会话 {session_id} 执行失败: {error_message}",
            code="RESEARCH_FAILED",
        )
        self.session_id = session_id
        self.error_message = error_message


class InvalidResearchQueryError(DeepResearchError):
    """无效的研究查询"""
    _serializable_attrs: ClassVar[List[str]] = ["reason"]

    def __init__(self, reason: str):
        super().__init__(
            message=f"研究查询无效: {reason}",
            code="INVALID_RESEARCH_QUERY",
        )
        self.reason = reason


class SearchProviderNotConfiguredError(DeepResearchError):
    """搜索服务商未配置"""
    _serializable_attrs: ClassVar[List[str]] = ["provider"]

    def __init__(self, provider: str):
        super().__init__(
            message=f"外部搜索服务商 {provider} 未配置 API Key",
            code="SEARCH_PROVIDER_NOT_CONFIGURED",
        )
        self.provider = provider


class SearchProviderUnavailableError(DeepResearchError):
    """搜索服务商不可用"""
    _serializable_attrs: ClassVar[List[str]] = ["provider", "reason"]

    def __init__(self, provider: str, reason: str):
        super().__init__(
            message=f"外部搜索服务商 {provider} 不可用: {reason}",
            code="SEARCH_PROVIDER_UNAVAILABLE",
        )
        self.provider = provider
        self.reason = reason


class ResearchSpaceAccessDeniedError(DeepResearchError):
    """无权访问知识空间"""
    _serializable_attrs: ClassVar[List[str]] = ["space_id", "user_id"]

    def __init__(self, space_id: int, user_id: int):
        super().__init__(
            message=f"用户 {user_id} 无权访问知识空间 {space_id}",
            code="RESEARCH_SPACE_ACCESS_DENIED",
        )
        self.space_id = space_id
        self.user_id = user_id


class ResearchModeNotSupportedError(DeepResearchError):
    """不支持的研究模式"""
    _serializable_attrs: ClassVar[List[str]] = ["mode"]

    def __init__(self, mode: str):
        super().__init__(
            message=f"不支持的研究模式: {mode}",
            code="RESEARCH_MODE_NOT_SUPPORTED",
        )
        self.mode = mode


class ResearchRunningError(DeepResearchError):
    """研究正在运行中，无法删除"""
    _serializable_attrs: ClassVar[List[str]] = ["session_id"]

    def __init__(self, session_id: str):
        super().__init__(
            message=f"研究会话 {session_id} 正在运行中，无法删除",
            code="RESEARCH_RUNNING",
        )
        self.session_id = session_id


class ResearchAccessDeniedError(DeepResearchError):
    """无权操作此研究记录"""
    _serializable_attrs: ClassVar[List[str]] = ["session_id", "user_id"]

    def __init__(self, session_id: str, user_id: int):
        super().__init__(
            message=f"用户 {user_id} 无权操作研究会话 {session_id}",
            code="RESEARCH_ACCESS_DENIED",
        )
        self.session_id = session_id
        self.user_id = user_id
