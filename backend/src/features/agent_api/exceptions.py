"""Agent API 模块异常（BaseAPIError 体系；http_status_code 显式声明在类自身
__dict__——不依赖 getattr 继承链，历史三连 bug 教训）。"""
from typing import ClassVar

from novamind.core.middleware.base_exception_handler import BaseAPIError


class AgentApiError(BaseAPIError):
    """Agent API 模块基础异常"""

    http_status_code: ClassVar[int] = 400

    def __init__(self, message: str, code: str = "AGENT_API_ERROR"):
        super().__init__(message=message, code=code)


class InvalidApiKeyError(AgentApiError):
    """API key 缺失/无效/已吊销/关联用户不可用——统一 401 不区分原因（防探测）"""

    http_status_code: ClassVar[int] = 401

    def __init__(self, message: str = "API key 无效或已吊销"):
        super().__init__(message=message, code="INVALID_API_KEY")


class ApiKeyNotFoundError(AgentApiError):
    """key 不存在或不属于当前用户（防横探：他人 key 同样 404）"""

    http_status_code: ClassVar[int] = 404

    def __init__(self, message: str = "API key 不存在"):
        super().__init__(message=message, code="API_KEY_NOT_FOUND")


class ApiKeyLimitExceededError(AgentApiError):
    """每用户 key 数量超上限"""

    http_status_code: ClassVar[int] = 409

    def __init__(self, message: str = "API key 数量已达上限"):
        super().__init__(message=message, code="API_KEY_LIMIT_EXCEEDED")
