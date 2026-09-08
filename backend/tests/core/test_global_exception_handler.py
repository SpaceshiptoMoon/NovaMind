"""全局异常处理器单测。

覆盖 ``global_exception_handler`` 对 ``BaseAPIError`` 子类的状态码选择逻辑：
子类未显式声明 ``http_status_code`` 时，应按 ``error_code`` 后缀/精确映射返回状态码；
子类显式声明时才优先使用声明值。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from novamind.core.middleware.base_exception_handler import (
    BaseAPIError,
    global_exception_handler,
)

pytestmark = pytest.mark.unit


class UserNotFoundError(BaseAPIError):
    """未显式覆盖 http_status_code 的业务异常。"""

    def __init__(self, message: str = "用户不存在") -> None:
        super().__init__(message=message, code="USER_NOT_FOUND")


class ExplicitForbiddenError(BaseAPIError):
    """显式覆盖 http_status_code 的业务异常。"""

    http_status_code = 403

    def __init__(self, message: str = "禁止访问") -> None:
        super().__init__(message=message, code="EXPLICIT_FORBIDDEN")


@pytest.fixture
def fake_request():
    request = MagicMock()
    request.state.trace_id = "trace-test"
    request.url.path = "/api/test"
    request.method = "GET"
    return request


@pytest.mark.asyncio
async def test_global_handler_maps_error_code_when_no_explicit_status(fake_request):
    """未显式声明 http_status_code 的 BaseAPIError 子类按 error_code 映射返回 404。"""
    exc = UserNotFoundError("用户未找到")
    response = await global_exception_handler(fake_request, exc)
    assert response.status_code == 404
    body = json.loads(response.body)
    assert body["error"]["code"] == "USER_NOT_FOUND"
    assert body["error"]["message"] == "用户未找到"


@pytest.mark.asyncio
async def test_global_handler_uses_explicit_http_status_code(fake_request):
    """显式声明 http_status_code 的 BaseAPIError 子类优先使用声明值 403。"""
    exc = ExplicitForbiddenError()
    response = await global_exception_handler(fake_request, exc)
    assert response.status_code == 403
