"""单元测试：OpenAI 兼容网关——鉴权双通道、/v1/models、OpenAI 错误格式。

覆盖：
- get_gateway_user 依赖：Bearer 优先 / X-API-Key 回落 / 双缺 401 /
  无效 key 401（GatewayAuthError）；成功写 request.state.user_id
- OpenAiGatewayService.list_models：去重 + created 取最早 + OpenAI 响应形状
- provider_error_to_openai：限流/额度/5xx/默认四类映射
- gateway_auth_error_handler：401 OpenAI 信封（message/type/param/code）
- 端到端（最小 app + httpx ASGITransport）：/v1/models 走真实路由链，
  验证 Bearer 鉴权 + OpenAI 错误格式不被统一信封污染

DB 交互 SQLite 内存库定向建表（复用 test_api_key_management 的基建模式）。
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _crypto_key():
    from novamind.shared.utils.crypto import configure_encryption_key

    configure_encryption_key("unit-test-encryption-key-not-a-secret")
    yield


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def key_db():
    from novamind.core.database.base import Base
    from novamind.features.agent_api.models.api_key import AgentApiKey
    from novamind.features.user.models.user import User

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[User.__table__, AgentApiKey.__table__]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


def _patch_user_status(active: bool):
    async def _fake(self, user_id):
        if not active:
            return None
        return {
            "id": user_id, "username": "tester", "email": "t@x.com",
            "role_code": "member", "is_admin": False, "status": 1,
            "is_active": active, "is_deleted": False, "must_change_password": False,
        }

    return patch(
        "novamind.features.user.services.user_service.UserService.get_auth_status",
        new=_fake,
    )


def _patch_touch():
    return patch(
        "novamind.features.agent_api.services.api_key_service.ApiKeyService._touch_last_used_safe",
        new=AsyncMock(return_value=None),
    )


@pytest_asyncio.fixture
async def seeded_key(key_db):
    """造一枚可用 key，返回 (plain, factory)。"""
    from novamind.features.agent_api.services.api_key_service import ApiKeyService

    factory, _ = key_db
    async with factory() as db:
        svc = ApiKeyService(db)
        with _patch_user_status(True), _patch_touch():
            _, plain = await svc.create_key(user_id=1, name="gw-key")
            await db.commit()
    return plain, factory


# ========== get_gateway_user 依赖 ==========


def _make_request(headers: dict[str, str] | None = None):
    from starlette.requests import Request

    raw = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    return Request({
        "type": "http", "headers": raw, "method": "GET",
        "url": "http://test/v1/models", "query_string": b"",
    })


@pytest.mark.asyncio
async def test_gateway_user_bearer_priority(seeded_key):
    """Bearer 与 X-API-Key 同时在时 Bearer 优先；成功写 request.state.user_id。"""
    from novamind.features.agent_api.api.dependencies import get_gateway_user, get_api_key_service

    plain, factory = seeded_key
    async with factory() as db:
        svc = await get_api_key_service(db)
        request = _make_request({
            "Authorization": f"Bearer {plain}",
            "X-API-Key": "nvm_wrong_key_not_valid_000000",
        })
        with _patch_user_status(True), _patch_touch():
            user = await get_gateway_user(
                request=request, authorization=f"Bearer {plain}",
                x_api_key="nvm_wrong_key_not_valid_000000", service=svc,
            )
    assert user["id"] == 1
    assert request.state.user_id == 1


@pytest.mark.asyncio
async def test_gateway_user_falls_back_to_x_api_key(seeded_key):
    """无 Authorization 时回落 X-API-Key（MCP/自研客户端兼容通道）。"""
    from novamind.features.agent_api.api.dependencies import get_gateway_user, get_api_key_service

    plain, factory = seeded_key
    async with factory() as db:
        svc = await get_api_key_service(db)
        request = _make_request({"X-API-Key": plain})
        with _patch_user_status(True), _patch_touch():
            user = await get_gateway_user(
                request=request, authorization=None, x_api_key=plain, service=svc,
            )
    assert user["id"] == 1


@pytest.mark.asyncio
async def test_gateway_user_missing_credentials_401(key_db):
    """Bearer/X-API-Key 双缺 → GatewayAuthError（401，OpenAI 格式源异常）。"""
    from novamind.features.agent_api.api.dependencies import get_gateway_user, get_api_key_service
    from novamind.features.agent_api.exceptions import GatewayAuthError

    factory, _ = key_db
    async with factory() as db:
        svc = await get_api_key_service(db)
        with pytest.raises(GatewayAuthError):
            await get_gateway_user(
                request=_make_request(), authorization=None, x_api_key=None, service=svc,
            )


@pytest.mark.asyncio
async def test_gateway_user_invalid_key_401(seeded_key):
    """无效 key → GatewayAuthError（管理端点的 InvalidApiKeyError 转译）。"""
    from novamind.features.agent_api.api.dependencies import get_gateway_user, get_api_key_service
    from novamind.features.agent_api.exceptions import GatewayAuthError

    _, factory = seeded_key
    async with factory() as db:
        svc = await get_api_key_service(db)
        with pytest.raises(GatewayAuthError):
            await get_gateway_user(
                request=_make_request(),
                authorization="Bearer nvm_invalid_key_not_valid_0000000000",
                x_api_key=None, service=svc,
            )


# ========== list_models ==========


@pytest.mark.asyncio
async def test_list_models_dedup_and_shape(key_db):
    """同名模型去重取最早 created；响应为 OpenAI list 形状。"""
    from datetime import datetime

    from novamind.features.agent_api.services.openai_gateway_service import OpenAiGatewayService

    class _Item:
        def __init__(self, model, created_at):
            self.model = model
            self.created_at = created_at

    class _Resp:
        items = [
            _Item("gpt-x", datetime(2026, 1, 2, 0, 0, 0)),
            _Item("gpt-x", datetime(2026, 1, 1, 0, 0, 0)),  # 更早 → 胜出
            _Item("qwen", datetime(2026, 1, 3, 0, 0, 0)),
        ]

    factory, _ = key_db
    async with factory() as db:
        with patch(
            "novamind.features.user.services.model_config_service.ModelConfigService.list_configs",
            new=AsyncMock(return_value=_Resp()),
        ):
            body = await OpenAiGatewayService(db).list_models(user_id=1)

    assert body["object"] == "list"
    ids = [m["id"] for m in body["data"]]
    assert ids == ["gpt-x", "qwen"]  # 排序 + 去重
    gpt = body["data"][0]
    assert gpt["object"] == "model"
    assert gpt["created"] == int(datetime(2026, 1, 1, 0, 0, 0).timestamp())
    assert gpt["owned_by"] == "novamind"


# ========== provider_error_to_openai 映射 ==========


def test_quota_error_maps_to_insufficient_quota():
    from novamind.features.agent_api.services.openai_gateway_service import (
        provider_error_to_openai,
    )
    from novamind.shared.ai_models.errors import ModelQuotaError

    status, body = provider_error_to_openai(ModelQuotaError("额度耗尽"))
    assert status == 400
    assert body["error"]["code"] == "insufficient_quota"
    assert body["error"]["type"] == "invalid_request_error"


def test_rate_limit_maps_to_429():
    from novamind.features.agent_api.services.openai_gateway_service import (
        provider_error_to_openai,
    )
    from novamind.shared.ai_models.errors import ModelRateLimitError

    status, body = provider_error_to_openai(ModelRateLimitError("限流"))
    assert status == 429
    assert body["error"]["type"] == "rate_limit_error"


def test_provider_5xx_maps_to_api_error():
    from novamind.features.agent_api.services.openai_gateway_service import (
        provider_error_to_openai,
    )
    from novamind.shared.ai_models.errors import ModelProviderError

    status, body = provider_error_to_openai(ModelProviderError("炸了", status_code=503))
    assert status == 503
    assert body["error"]["type"] == "api_error"


def test_unknown_status_defaults_502():
    from novamind.features.agent_api.services.openai_gateway_service import (
        provider_error_to_openai,
    )
    from novamind.shared.ai_models.errors import ModelProviderError

    status, body = provider_error_to_openai(ModelProviderError("无状态码"))
    assert status == 502
    assert body["error"]["type"] == "invalid_request_error"


# ========== 异常处理器 + 最小 app 端到端 ==========


@pytest_asyncio.fixture
async def gateway_app(key_db):
    """最小 FastAPI app：真路由 + dependency_overrides 注入测试库会话。"""
    from fastapi import FastAPI
    from novamind.core.database.database import get_db
    from novamind.features.agent_api.api.exception_handlers import (
        setup_agent_api_exception_handlers,
    )
    from novamind.features.agent_api.api.gateway_routes import router as gateway_router
    from novamind.features.agent_api.api.key_routes import router as key_router

    factory, _ = key_db

    async def _override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(key_router, prefix="/api/v1/agent-api")
    app.include_router(gateway_router, prefix="/v1")
    setup_agent_api_exception_handlers(app)
    app.dependency_overrides[get_db] = _override_db
    return app


@pytest.mark.asyncio
async def test_models_endpoint_end_to_end(gateway_app, seeded_key):
    """正例端到端：Bearer 鉴权 → /v1/models 返回 OpenAI 形状（list_configs 打桩）。"""
    from datetime import datetime
    from unittest.mock import patch as sync_patch

    plain, _ = seeded_key

    class _Item:
        model = "gpt-x"
        created_at = datetime(2026, 1, 1)

    class _Resp:
        items = [_Item()]
        total = 1

    # list_configs 是 async 方法，AsyncMock 挂在类上（懒 import 点在 service 内）；
    # 鉴权走真实 authenticate 链 → get_auth_status/_touch_last_used_safe 同样打桩
    with sync_patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.list_configs",
        new=AsyncMock(return_value=_Resp()),
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/v1/models", headers={"Authorization": f"Bearer {plain}"}
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert [m["id"] for m in body["data"]] == ["gpt-x"]


@pytest.mark.asyncio
async def test_models_endpoint_wrong_key_openai_error(gateway_app):
    """无效 key → 401 且响应体是 OpenAI 错误信封（非统一信封——防格式泄漏）。"""
    transport = ASGITransport(app=gateway_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/models", headers={"Authorization": "Bearer nvm_bad_key_not_valid_00000000"}
        )

    assert resp.status_code == 401
    body = resp.json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == "invalid_api_key"
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["param"] is None


@pytest.mark.asyncio
async def test_models_endpoint_no_auth_openai_error(gateway_app):
    """无鉴权头 → 401 OpenAI 信封，message 提示两种可用的凭证方式。"""
    transport = ASGITransport(app=gateway_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/models")

    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "invalid_api_key"
    assert "Bearer" in body["error"]["message"]
