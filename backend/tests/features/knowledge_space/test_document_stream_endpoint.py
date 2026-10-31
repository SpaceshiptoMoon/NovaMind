"""视频流式播放端点（HTTP Range 206）与媒体标签鉴权依赖的回归测试。

覆盖：
- _parse_single_range：单区间三种形态 / 多区间与非法回退 None / 越界回退
- /stream：206 分段头与体、无 Range 全量 200、后缀区间、越界宽容兜底、
  显式 video MIME（mkv 不靠 mimetypes）、inline 文件名、非视频 400
- get_current_user_media：Authorization 头优先、?token= 兜底、都缺 401
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import novamind.core.auth.dependencies as auth_deps
import novamind.features.knowledge_space.api.document_routes as routes_module
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from novamind.core.auth import get_current_user_media
from novamind.core.auth.dependencies import get_user_status_resolver
from novamind.core.auth.exceptions import AuthenticationError
from novamind.core.database.database import get_db
from novamind.features.knowledge_space.api.dependencies import (
    get_document_query_service,
)
from novamind.features.knowledge_space.api.document_routes import (
    _parse_single_range,
    router,
)
from novamind.features.knowledge_space.exceptions import InvalidParameterError
from novamind.features.knowledge_space.models.space_member import SpaceMember

pytestmark = pytest.mark.unit

_PAYLOAD = bytes(range(32))  # 32 字节可区分内容


# ---------------------------------------------------------------------------
# _parse_single_range 纯函数
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header, size, expected",
    [
        ("bytes=0-", 100, (0, 100)),
        ("bytes=10-19", 100, (10, 20)),
        ("bytes=90-999", 100, (90, 100)),      # end 越界截到文件尾
        ("bytes=-10", 100, (90, 100)),         # 后缀区间
        ("bytes=-500", 100, (0, 100)),         # 后缀超过总长取全量
        ("BYTES=5-5", 100, (5, 6)),            # 单位大小写不敏感
        ("bytes=100-", 100, None),             # start 越界 → 兜底全量
        ("bytes=0-10,20-30", 100, None),       # 多区间不支持
        ("items=0-10", 100, None),             # 非 bytes 单位
        ("bytes=abc-", 100, None),             # 语法非法
        ("bytes=-0", 100, None),               # 零长后缀
        ("bytes=0-", 0, None),                 # 空对象
    ],
)
def test_parse_single_range(header, size, expected):
    """单区间解析矩阵：合法形态得半开区间，其余一律 None 由调用方按全量兜底。"""
    assert _parse_single_range(header, size) == expected


# ---------------------------------------------------------------------------
# /stream 端点
# ---------------------------------------------------------------------------


def _document(file_type: str = "mp4", filename: str = "演示视频.mp4", size: int = len(_PAYLOAD)):
    return SimpleNamespace(id=9, kb_id=1, filename=filename, file_type=file_type, file_size=size)


def _build_app(document, range_calls: list[tuple[int, int]]):
    """只挂文档路由的极简 app；open_document_range 桩按区间切 _PAYLOAD 并记录调用。"""
    app = FastAPI()
    app.include_router(router, prefix="/spaces/{space_id}/kb")

    original_kb_access = routes_module.validate_kb_access
    routes_module.validate_kb_access = AsyncMock(return_value=None)

    def open_document_range(doc, start, length):
        range_calls.append((start, length))
        data = _PAYLOAD[start:start + length]
        return iter([data[:7], data[7:]])  # 两块，验证流式拼接

    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    app.dependency_overrides[get_current_user_media] = lambda: {"id": 1}
    app.dependency_overrides[get_document_query_service] = lambda: SimpleNamespace(
        get_document=AsyncMock(return_value=document),
        open_document_range=open_document_range,
    )

    # ensure_space_member 在路由体内被直接 await 调用（非 Depends），与
    # validate_kb_access 一样只能 patch 路由模块命名空间的名字
    original_ensure_member = routes_module.ensure_space_member
    routes_module.ensure_space_member = AsyncMock(
        return_value=SpaceMember(id=1, space_id=1, user_id=1, role="editor"),
    )

    import atexit

    def _restore():
        routes_module.validate_kb_access = original_kb_access
        routes_module.ensure_space_member = original_ensure_member

    atexit.register(_restore)
    return app


async def _stream(document, headers: dict | None = None):
    calls: list[tuple[int, int]] = []
    app = _build_app(document, calls)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/spaces/1/kb/1/documents/9/stream", headers=headers or {})
    return resp, calls


def test_range_request_returns_206_with_partial_body():
    """bytes=2-5 → 206、Content-Range/Length 正确、体为对应切片、MinIO 只读该区间。"""
    resp, calls = asyncio.run(_stream(_document(), {"Range": "bytes=2-5"}))

    assert resp.status_code == 206
    assert resp.content == _PAYLOAD[2:6]
    assert resp.headers["content-range"] == f"bytes 2-5/{len(_PAYLOAD)}"
    assert resp.headers["content-length"] == "4"
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["content-type"].startswith("video/mp4")
    assert resp.headers["content-disposition"].startswith("inline;")
    assert calls == [(2, 4)]


def test_no_range_returns_full_200_stream():
    """无 Range：200 全量流，Content-Length 为文件大小，仍宣告 Accept-Ranges。"""
    resp, calls = asyncio.run(_stream(_document()))

    assert resp.status_code == 200
    assert resp.content == _PAYLOAD
    assert resp.headers["content-length"] == str(len(_PAYLOAD))
    assert resp.headers["accept-ranges"] == "bytes"
    assert "content-range" not in resp.headers
    assert calls == [(0, len(_PAYLOAD))]


def test_suffix_range_returns_tail():
    """bytes=-4 → 末尾 4 字节。"""
    resp, calls = asyncio.run(_stream(_document(), {"Range": "bytes=-4"}))

    n = len(_PAYLOAD)
    assert resp.status_code == 206
    assert resp.content == _PAYLOAD[-4:]
    assert resp.headers["content-range"] == f"bytes {n - 4}-{n - 1}/{n}"
    assert calls == [(n - 4, 4)]


def test_out_of_bounds_range_falls_back_to_full():
    """start 越界的 Range 不报 416，宽容退化为 200 全量（播放器仍可播）。"""
    resp, calls = asyncio.run(_stream(_document(), {"Range": "bytes=999-"}))

    assert resp.status_code == 200
    assert resp.content == _PAYLOAD
    assert calls == [(0, len(_PAYLOAD))]


def test_mkv_mime_is_explicit_not_mimetypes():
    """mkv 走显式映射 video/x-matroska（mimetypes 在部分系统猜不出）。"""
    resp, _ = asyncio.run(_stream(_document(file_type="mkv", filename="a.mkv"), {"Range": "bytes=0-"}))

    assert resp.status_code == 206
    assert resp.headers["content-type"].startswith("video/x-matroska")


def test_non_video_document_rejected_with_400():
    """非视频类型请求流式端点 → InvalidParameterError（400 语义），不读存储。"""
    with pytest.raises(InvalidParameterError):
        asyncio.run(_stream(_document(file_type="pdf", filename="a.pdf")))


# ---------------------------------------------------------------------------
# get_current_user_media：头优先 / query 兜底 / 都缺 401
# ---------------------------------------------------------------------------


def _build_auth_probe_app(monkeypatch, seen: list[str]):
    """挂一个只依赖 get_current_user_media 的探针路由；记录实际用于校验的 token。"""
    async def fake_resolve(token, resolver, *, enforce_password_change=False, request=None):
        seen.append(token)
        return {"id": 7, "username": "u"}

    monkeypatch.setattr(auth_deps, "_resolve_user_from_token", fake_resolve)

    app = FastAPI()

    @app.get("/probe")
    async def probe(user: dict = Depends(get_current_user_media)):
        return {"id": user["id"]}

    app.dependency_overrides[get_user_status_resolver] = lambda: object()
    return app


async def _probe(app, url: str, headers: dict | None = None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(url, headers=headers or {})


def test_media_auth_query_token_fallback(monkeypatch):
    """无 Authorization 头时用 ?token= 校验（媒体标签场景）。"""
    seen: list[str] = []
    app = _build_auth_probe_app(monkeypatch, seen)

    resp = asyncio.run(_probe(app, "/probe?token=query-jwt"))

    assert resp.status_code == 200 and resp.json() == {"id": 7}
    assert seen == ["query-jwt"]


def test_media_auth_header_takes_precedence_over_query(monkeypatch):
    """头与查询串同时存在：以 Authorization 头为准。"""
    seen: list[str] = []
    app = _build_auth_probe_app(monkeypatch, seen)

    resp = asyncio.run(_probe(app, "/probe?token=query-jwt", {"Authorization": "Bearer header-jwt"}))

    assert resp.status_code == 200
    assert seen == ["header-jwt"]


def test_media_auth_missing_both_raises_401(monkeypatch):
    """头与查询串都缺：缺凭证 AuthenticationError（401 语义），不进入 token 校验。"""
    seen: list[str] = []
    app = _build_auth_probe_app(monkeypatch, seen)

    with pytest.raises(AuthenticationError):
        asyncio.run(_probe(app, "/probe"))
    assert seen == []
