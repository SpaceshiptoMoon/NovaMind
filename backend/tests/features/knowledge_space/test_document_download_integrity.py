"""批1 c5 回归：文档下载响应带端到端完整性头（ETag + X-Checksum-SHA256）。

背景：大视频经 nginx/代理链路下载缺少端到端完整性凭证。file_hash（上传时
计算的 sha256，DB 权威值）以响应头形式下发，客户端可显式校验传输完整性；
file_hash 缺失（历史数据）时头优雅缺席，不影响下载本身。
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import novamind.features.knowledge_space.api.document_routes as routes_module
from novamind.core.database.database import get_db
from novamind.features.knowledge_space.api.dependencies import (
    get_current_user_id,
    get_document_query_service,
    validate_kb_access,
    validate_space_member,
)
from novamind.features.knowledge_space.api.document_routes import router
from novamind.features.knowledge_space.models.space_member import SpaceMember

pytestmark = pytest.mark.unit

_SHA = "a" * 64


def _build_app(document, download_bytes=b"file-bytes"):
    """组装只挂下载路由的极简 app。

    依赖覆盖必须走 dependency_overrides（key = 原 dependency 函数对象）——
    路由注册时 FastAPI 已捕获原对象，事后 patch 模块属性不生效。
    override 值必须是签名明确的函数——AsyncMock 签名是 (*args, **kwargs)，
    FastAPI 会把可变参数当必填 query 参数（422 Field required）。
    """
    app = FastAPI()
    app.include_router(router, prefix="/spaces/{space_id}/kb")

    # validate_kb_access 在路由体内被直接 await 调用（非 Depends），必须 patch
    # 路由模块命名空间的名字才拦得住；permission 语义不是本测试的被测对象
    original_kb_access = routes_module.validate_kb_access
    routes_module.validate_kb_access = AsyncMock(return_value=None)

    class _FakeSession:
        async def execute(self, *a, **k):
            class _R:
                def scalar_one_or_none(self):
                    return None
            return _R()

    app.dependency_overrides[get_db] = lambda: _FakeSession()
    app.dependency_overrides[get_current_user_id] = lambda: 1
    app.dependency_overrides[validate_space_member] = lambda: SpaceMember(
        id=1, space_id=1, user_id=1, role="editor",
    )
    app.dependency_overrides[get_document_query_service] = lambda: SimpleNamespace(
        get_document=AsyncMock(return_value=document),
        download_document=AsyncMock(return_value=download_bytes),
    )

    import atexit

    def _restore():
        routes_module.validate_kb_access = original_kb_access

    atexit.register(_restore)
    return app


async def _get_headers(document):
    app = _build_app(document)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/spaces/1/kb/1/documents/9/download")
    assert resp.status_code == 200
    return resp.headers, resp.content


def test_download_response_carries_integrity_headers():
    """有 file_hash 的文档：ETag（带引号）与 X-Checksum-SHA256 同时下发。"""
    import asyncio

    document = SimpleNamespace(
        id=9, kb_id=1, filename="烹饪演示.mp4", file_hash=_SHA,
    )
    headers, content = asyncio.run(_get_headers(document))

    assert content == b"file-bytes"
    assert headers.get("etag") == f'"{_SHA}"'
    assert headers.get("x-checksum-sha256") == _SHA


def test_download_response_without_hash_omits_headers():
    """历史文档无 file_hash：完整性头缺席，下载本身不受影响（能力缺失方向安全）。"""
    import asyncio

    document = SimpleNamespace(
        id=9, kb_id=1, filename="old.pdf", file_hash=None,
    )
    headers, content = asyncio.run(_get_headers(document))

    assert content == b"file-bytes"
    assert "etag" not in headers
    assert "x-checksum-sha256" not in headers
