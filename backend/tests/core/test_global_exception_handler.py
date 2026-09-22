"""全局异常处理器单测。

覆盖 ``global_exception_handler`` 对 ``BaseAPIError`` 子类的状态码选择逻辑：
子类未显式声明 ``http_status_code`` 时，应按 ``error_code`` 后缀/精确映射返回状态码；
子类显式声明时才优先使用声明值。

另覆盖 2026-09-22 修复的认证异常 500 bug：
core/auth 与 features/user 各有一个同名不同源的 ``AuthenticationError``（无继承关系），
Starlette 按类沿 MRO 精确匹配 handler——两边都必须以正确类注册，且
``BaseAPIError`` 专属兜底处理器保证未注册专属 handler 的业务异常响应可靠送达
（此前依赖层抛出穿越 BaseHTTPMiddleware 后被 re-raise 到 uvicorn，客户端收 500）。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from novamind.core.middleware.base_exception_handler import (
    BaseAPIError,
    base_api_error_handler,
    global_exception_handler,
    setup_global_exception_handlers,
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


# ==================== 认证异常 500 bug 回归（2026-09-22） ====================


def test_dual_authentication_errors_both_resolve_to_401():
    """core/auth 与 features/user 两个同名 AuthenticationError 都命中 401 handler。

    Starlette 按类沿 MRO 精确匹配：完整 app 装配（setup_user_exception_handlers
    注册 user 版专属 + setup_global_exception_handlers 注册 BaseAPIError 兜底）后，
    两个类各自解析到返回 401 的 handler，而非落到 Exception 兜底。
    """
    from novamind.core.auth.exceptions import AuthenticationError as CoreAuthError
    from novamind.features.user.api.startup import setup_user_exception_handlers
    from novamind.features.user.exceptions import AuthenticationError as UserAuthError

    # 前提断言：确实是同名不同源的两个类（回归 bug 的成因）
    assert CoreAuthError is not UserAuthError
    assert not issubclass(CoreAuthError, UserAuthError)
    assert not issubclass(UserAuthError, CoreAuthError)

    app = FastAPI()
    setup_user_exception_handlers(app)
    setup_global_exception_handlers(app)

    # 关键断言：两类沿 MRO 解析到的都不是 Exception 兜底 handler
    for exc_cls in (CoreAuthError, UserAuthError):
        resolved = next(
            cls for cls in exc_cls.__mro__ if cls in app.exception_handlers
        )
        handler = app.exception_handlers[resolved]
        assert handler is not global_exception_handler, (
            f"{exc_cls.__module__}.{exc_cls.__name__} 落到了 Exception 兜底（会 500）"
        )


@pytest.mark.asyncio
async def test_base_api_error_handler_returns_declared_status(fake_request):
    """BaseAPIError 专属兜底处理器按类声明的 http_status_code 返回响应。"""
    from novamind.core.auth.exceptions import AuthenticationError

    exc = AuthenticationError("无效的认证凭证")
    response = await base_api_error_handler(fake_request, exc)
    assert response.status_code == 401
    body = json.loads(response.body)
    assert body["error"]["code"] == "AUTHENTICATION_FAILED"
    assert body["error"]["message"] == "无效的认证凭证"


@pytest.mark.asyncio
async def test_unregistered_base_api_error_subclass_falls_back_to_500_mapping():
    """未声明 http_status_code 且 error_code 无法映射的子类经兜底返回 500（非穿透）。"""
    from httpx import ASGITransport, AsyncClient

    class WeirdError(BaseAPIError):
        def __init__(self):
            super().__init__(message="奇怪错误", code="TOTALLY_UNKNOWN_CODE_XYZ")

    app = FastAPI()
    setup_global_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise WeirdError()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/boom")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "TOTALLY_UNKNOWN_CODE_XYZ"


@pytest.mark.asyncio
async def test_auth_error_through_dependency_returns_401_not_500():
    """端到端：依赖层抛 core auth AuthenticationError，客户端收到 401（修复前收 500）。"""
    from novamind.core.auth.exceptions import (
        AuthenticationError,
        AuthenticationRevokedError,
    )
    from novamind.features.user.api.startup import setup_user_exception_handlers

    app = FastAPI()
    setup_user_exception_handlers(app)
    setup_global_exception_handlers(app)

    @app.get("/protected")
    async def protected():
        raise AuthenticationError("无效的认证凭证")

    @app.get("/revoked")
    async def revoked():
        raise AuthenticationRevokedError("登录凭证已撤销，请重新登录")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r401 = await client.get("/protected")
        r401b = await client.get("/revoked")
    assert r401.status_code == 401
    assert r401.json()["error"]["code"] == "AUTHENTICATION_FAILED"
    assert r401b.status_code == 401
    assert r401b.json()["error"]["code"] == "AUTHENTICATION_REVOKED"
