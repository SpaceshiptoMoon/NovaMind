# -*- coding: utf-8 -*-
"""回归门禁：create_error_handler 的状态码解析不得沿 MRO 继承 BaseAPIError 的 500。

根因回顾（2026-09-23 接口全量测试发现）：create_error_handler 曾用
``getattr(type(exc), "http_status_code", default)``——getattr 沿 MRO 命中
``BaseAPIError.http_status_code: ClassVar[int] = 500``，令所有模块级
status_map（SpaceNotFoundError:404、AuthenticationError:401、
UserAlreadyExistsError:409 等）失效，全部返回 500。6a0bd00 与 fa794b8
修过 global/base 兜底两个 handler 的同根因，此处补齐第三处。
"""
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, "backend")

from novamind.core.middleware.base_exception_handler import BaseAPIError


class _FakeNotFound(BaseAPIError):
    """模拟「未声明 http_status_code、靠 status_map 注册 404」的模块异常。"""

    def __init__(self):
        super().__init__(message="资源不存在", code="SOMETHING_NOT_FOUND")


class _FakeConflict(BaseAPIError):
    def __init__(self):
        super().__init__(message="已存在", code="SOMETHING_ALREADY_EXISTS")


class _FakeAuthFailed(BaseAPIError):
    def __init__(self):
        super().__init__(message="认证失败", code="AUTHENTICATION_FAILED")


def _make_client():
    from novamind.core.middleware.base_exception_handler import (
        register_module_exceptions,
    )

    app = FastAPI()
    register_module_exceptions(app, status_map={
        _FakeNotFound: 404,
        _FakeConflict: 409,
        _FakeAuthFailed: 401,
    })

    @app.get("/nf")
    async def nf():
        raise _FakeNotFound()

    @app.post("/cf")
    async def cf():
        raise _FakeConflict()

    @app.get("/au")
    async def au():
        raise _FakeAuthFailed()

    return TestClient(app, raise_server_exceptions=False)


def test_status_map_honored_not_shadowed_by_base_class_500():
    """status_map 注册的 404/409/401 必须生效，不被基类 500 遮蔽。"""
    client = _make_client()
    assert client.get("/nf").status_code == 404
    assert client.post("/cf").status_code == 409
    assert client.get("/au").status_code == 401


def test_class_level_http_status_code_still_wins():
    """类自身显式声明的 http_status_code 仍优先于 status_map。"""
    from novamind.core.middleware.base_exception_handler import (
        create_error_handler,
        register_module_exceptions,
    )

    class _Declared409(_FakeNotFound):
        http_status_code = 409

    app = FastAPI()
    register_module_exceptions(app, status_map={_Declared409: 404})
    # add_exception_handler 相同异常类会覆盖，直接手动注册第二个 handler 验证优先级
    app.add_exception_handler(_Declared409, create_error_handler(404, "测试"))

    @app.get("/x")
    async def x():
        raise _Declared409()

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/x").status_code == 409


def test_unmapped_module_exception_falls_back_to_default():
    """未列入 status_map 的异常走 default_status_code（这里 418 自定义便于断言）。"""
    from novamind.core.middleware.base_exception_handler import (
        create_error_handler,
        register_module_exceptions,
    )

    class _Other(BaseAPIError):
        def __init__(self):
            super().__init__(message="其他", code="OTHER_ERROR")

    app = FastAPI()
    # 只注册 _Other 自身用 default=418
    app.add_exception_handler(_Other, create_error_handler(418, "测试默认"))

    @app.get("/o")
    async def o():
        raise _Other()

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/o").status_code == 418
