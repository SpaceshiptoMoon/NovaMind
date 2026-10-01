"""知识运营模块异常（BaseAPIError 体系；http_status_code 显式声明在类自身
__dict__——不依赖 getattr 继承链，历史三连 bug 教训）。"""
from typing import ClassVar

from novamind.core.middleware.base_exception_handler import BaseAPIError


class KbOpsError(BaseAPIError):
    """知识运营模块基础异常"""

    http_status_code: ClassVar[int] = 400

    def __init__(self, message: str, code: str = "KB_OPS_ERROR"):
        super().__init__(message=message, code=code)


class KbOpsNotFoundError(KbOpsError):
    """运营资源不存在（建议/事件等）"""

    http_status_code: ClassVar[int] = 404

    def __init__(self, message: str = "资源不存在"):
        super().__init__(message=message, code="KB_OPS_NOT_FOUND")
