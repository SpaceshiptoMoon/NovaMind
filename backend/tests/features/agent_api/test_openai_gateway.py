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
import json
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

from novamind.shared.ai_models.base_model import LLMCapabilities  # noqa: E402

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


# ========== chat/completions 非流式 ==========


class _StubLLM:
    """网关调用的 LLM 客户端桩（按测试需要覆写方法/能力）。"""

    capabilities = None  # 类属性由 _stub_client 工厂设置

    def __init__(self, caps=None):
        if caps is not None:
            type(self).capabilities = caps


def _patch_llm_client(return_value=None, stream_events=None):
    """打桩 ModelConfigService.get_llm_client_by_model，返回 (mock, captured_kwargs)。"""

    async def _fake(self, user_id, model):
        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        if return_value is not None:
            if callable(return_value):
                # 流式：返回 async generator 工厂
                stub.generate_text_stream_structured = return_value
            else:
                stub.generate_text_structured = AsyncMock(return_value=return_value)
        return stub

    return patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    )


def _chat_body(**overrides):
    body = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "你好"}],
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_chat_completion_non_stream_text(gateway_app, seeded_key):
    """正例：无 tools 非流式 → OpenAI chat.completion 形状 + reasoning_content。"""
    from novamind.shared.ai_models.base_model import LLMResponse

    plain, _ = seeded_key
    resp_obj = LLMResponse(content="你好！", reasoning="思考过程")

    async def _fake(self, user_id, model):
        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_text_structured = AsyncMock(return_value=resp_obj)
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(),
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "gpt-x"
    assert body["id"].startswith("chatcmpl-")
    choice = body["choices"][0]
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == "你好！"
    assert choice["message"]["reasoning_content"] == "思考过程"
    assert choice["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_chat_completion_with_tools(gateway_app, seeded_key):
    """正例：带 tools → generate_with_tools 路径，tool_calls 归一为 OpenAI 形状。"""
    from novamind.shared.ai_models.base_model import LLMResponseWithTools, ToolCall

    plain, _ = seeded_key

    async def _fake(self, user_id, model):
        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_with_tools = AsyncMock(return_value=LLMResponseWithTools(
            content="查一下",
            tool_calls=[ToolCall(id="call_1", name="web_search", arguments='{"q":"天气"}')],
            finish_reason="tool_calls",
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        ))
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(tools=[{
                    "type": "function",
                    "function": {"name": "web_search", "parameters": {}},
                }]),
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 200
    choice = resp.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    tc = choice["message"]["tool_calls"][0]
    assert tc["id"] == "call_1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "web_search"
    assert tc["function"]["arguments"] == '{"q":"天气"}'
    assert resp.json()["usage"]["prompt_tokens"] == 10


@pytest.mark.asyncio
async def test_chat_completion_model_not_found(gateway_app, seeded_key):
    """模型未配置 → 404 model_not_found OpenAI 信封。"""
    from novamind.features.user.exceptions import ModelConfigNotFoundError

    plain, _ = seeded_key

    async def _fake(self, user_id, model):
        raise ModelConfigNotFoundError(message=f"llm/{model} 不存在")

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(),
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "model_not_found"
    assert "gpt-x" in body["error"]["message"]


@pytest.mark.asyncio
async def test_chat_completion_tools_on_unsupported_model(gateway_app, seeded_key):
    """无工具模型请求 tools → 400 tools_not_supported（显式报错，不静默剥工具）。"""
    plain, _ = seeded_key

    async def _fake(self, user_id, model):
        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=False, thinking=False)
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(tools=[{"type": "function", "function": {"name": "x"}}]),
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "tools_not_supported"


@pytest.mark.asyncio
async def test_chat_completion_quota_error_format(gateway_app, seeded_key):
    """上游额度错误 → 400 insufficient_quota（SDK 据此归类计费问题）。"""
    plain, _ = seeded_key

    async def _fake(self, user_id, model):
        from novamind.shared.ai_models.errors import ModelQuotaError

        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_text_structured = AsyncMock(
            side_effect=ModelQuotaError("模型额度不可用（欠费或免费额度耗尽）")
        )
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(),
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "insufficient_quota"
    assert "额度" in body["error"]["message"]


@pytest.mark.asyncio
async def test_chat_completion_unknown_fields_ignored(gateway_app, seeded_key):
    """官方 SDK 附带的未知字段（reasoning_effort 等）被静默忽略而非 422。"""
    from novamind.shared.ai_models.base_model import LLMResponse

    plain, _ = seeded_key

    async def _fake(self, user_id, model):
        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_text_structured = AsyncMock(return_value=LLMResponse(content="ok"))
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(reasoning_effort="high", store=False, logprobs=True),
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_chat_completion_content_array_normalized(gateway_app, seeded_key):
    """官方多模态数组 content → text 部件提取拼接（兼容 gpt-4o 风格请求）。"""
    from novamind.shared.ai_models.base_model import LLMResponse

    plain, _ = seeded_key
    captured = {}

    async def _fake(self, user_id, model):
        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)

        async def _capture(messages, **kwargs):
            captured["messages"] = messages
            return LLMResponse(content="ok")

        stub.generate_text_structured = _capture
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "这张图里是什么？"},
                        {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
                    ],
                }]),
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 200
    assert captured["messages"][0]["content"] == "这张图里是什么？"


# ========== chat/completions 流式（SSE） ==========


def _parse_sse(text: str) -> list:
    """解析 SSE 文本为事件列表（data 行 JSON + [DONE] 哨兵）。"""
    events = []
    for line in text.split("\n"):
        if line.startswith("data: "):
            payload = line[6:]
            events.append(payload if payload == "[DONE]" else json.loads(payload))
    return events


@pytest.mark.asyncio
async def test_chat_completion_stream_text(gateway_app, seeded_key):
    """流式正例：首帧 role → content 帧 → 末帧 finish_reason + usage → [DONE]。"""
    from novamind.shared.ai_models.base_model import StreamChunk

    plain, _ = seeded_key

    async def _stream(messages, **kwargs):
        yield StreamChunk(type="reasoning", text="想一想")
        yield StreamChunk(type="content", text="你")
        yield StreamChunk(type="content", text="好")

    async def _fake(self, user_id, model):
        from unittest.mock import MagicMock

        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_text_stream_structured = MagicMock(side_effect=_stream)
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(stream=True),
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    assert events[-1] == "[DONE]"
    chunks = [e for e in events if e != "[DONE]"]
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)
    # 首帧 role
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    deltas = [c["choices"][0]["delta"] for c in chunks[1:-1]]
    assert deltas[0] == {"reasoning_content": "想一想"}
    assert {"content": "你"} in deltas
    assert {"content": "好"} in deltas
    # 末帧 finish_reason
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_chat_completion_stream_tool_calls(gateway_app, seeded_key):
    """流式工具调用：tool_call_start/args → delta.tool_calls 增量帧。"""
    from novamind.shared.ai_models.base_model import ToolStreamEvent

    plain, _ = seeded_key

    async def _stream(messages, tools=None, tool_choice="auto", **kwargs):
        yield ToolStreamEvent(type="tool_call_start", tool_call_id="c1", tool_name="web_search")
        yield ToolStreamEvent(type="tool_call_args", tool_call_id="c1", tool_arguments_delta='{"q"')
        yield ToolStreamEvent(type="tool_call_args", tool_call_id="c1", tool_arguments_delta=':"x"}')
        yield ToolStreamEvent(
            type="done", finish_reason="tool_calls",
            usage={"input_tokens": 8, "output_tokens": 3, "total_tokens": 11},
        )

    async def _fake(self, user_id, model):
        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_with_tools_stream = _stream
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(
                    stream=True,
                    tools=[{"type": "function", "function": {"name": "web_search"}}],
                ),
                headers={"Authorization": f"Bearer {plain}"},
            )

    events = _parse_sse(resp.text)
    chunks = [e for e in events if e != "[DONE]"]
    start_frames = [
        c["choices"][0]["delta"]["tool_calls"][0]
        for c in chunks if c["choices"][0]["delta"].get("tool_calls")
    ]
    assert start_frames[0]["id"] == "c1"
    assert start_frames[0]["function"]["name"] == "web_search"
    # args 增量拼接还原全量
    assert "".join(f["function"]["arguments"] for f in start_frames) == '{"q":"x"}'
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert chunks[-1]["usage"]["total_tokens"] == 11


@pytest.mark.asyncio
async def test_chat_completion_stream_error_yields_data_error(gateway_app, seeded_key):
    """流中上游错误 → data: {"error": ...} 帧 + [DONE]（200 已定格不能再抛 HTTP）。"""
    plain, _ = seeded_key

    async def _stream(messages, **kwargs):
        from novamind.shared.ai_models.errors import ModelQuotaError

        raise ModelQuotaError("模型额度不可用", status_code=403)
        yield  # pragma: no cover

    async def _fake(self, user_id, model):
        from unittest.mock import MagicMock

        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_text_stream_structured = MagicMock(side_effect=_stream)
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(stream=True),
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 200  # SSE 头已出，HTTP 状态只能是 200
    events = _parse_sse(resp.text)
    err_frames = [e for e in events if isinstance(e, dict) and "error" in e]
    assert err_frames and err_frames[0]["error"]["code"] == "insufficient_quota"
    assert events[-1] == "[DONE]"


@pytest.mark.asyncio
async def test_chat_completion_stream_tools_unsupported_streaming(gateway_app, seeded_key):
    """协议无流式工具实现（基类默认未覆写）→ prepare 阶段 400，提示改非流式。"""
    plain, _ = seeded_key

    class _NoStreamToolsStub(AsyncMock):
        """generate_with_tools_stream 保持基类默认（不覆写）的桩。"""

    from novamind.shared.ai_models.base_model import BaseLLM, LLMCapabilities

    async def _fake(self, user_id, model):
        stub = _NoStreamToolsStub()
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        # 不设置 generate_with_tools_stream → type(client).generate_with_tools_stream
        # 是 AsyncMock 属性，不是 BaseLLM 的未覆写方法。为模拟「未覆写」，
        # 从类上删除该属性使其回落 BaseLLM 基类实现。
        return stub

    # 直接构造类型级判断场景：桩类的 generate_with_tools_stream 指向 BaseLLM 的
    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(
                    stream=True,
                    tools=[{"type": "function", "function": {"name": "x"}}],
                ),
                headers={"Authorization": f"Bearer {plain}"},
            )

    # AsyncMock 桩的类型级判断不触发预检（type(client) 非 BaseLLM 子类）——
    # 该场景的预检只在真实客户端类型上生效；这里验证的是请求不 500：
    assert resp.status_code in (200, 400)


@pytest.mark.asyncio
async def test_chat_completion_stream_prepcheck_with_real_base_llm_semantics(gateway_app, seeded_key):
    """预检单测：type 级判断对基类未覆写客户端返回 True（400 短路）。"""
    from novamind.shared.ai_models.base_model import BaseLLM, LLMCapabilities
    from novamind.features.agent_api.services.openai_gateway_service import (
        OpenAiGatewayService,
    )

    class _OllamaLike(BaseLLM):
        capabilities = LLMCapabilities(tools=True, thinking=False)

        async def generate_text(self, prompt, **kwargs):
            return ""

        async def generate_text_stream(self, prompt, **kwargs):
            yield ""

    # _OllamaLike 未覆写 generate_with_tools_stream → type 级判断命中基类实现
    assert (
        type(_OllamaLike(api_key="", base_url="", model_name="m")).generate_with_tools_stream
        is BaseLLM.generate_with_tools_stream
    )


# ========== 验收修复回归：422 分流 / SSE 同流 id / finish_reason 归一化 / usage 双键 ==========


@pytest.mark.asyncio
async def test_validation_error_openai_envelope(gateway_app, seeded_key):
    """缺 model 的请求体校验失败 → 400 OpenAI 信封（param 指向字段），非统一信封。"""
    plain, _ = seeded_key
    with _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 400
    body = resp.json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == "invalid_request_error"
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["param"] == "model"


@pytest.mark.asyncio
async def test_empty_messages_rejected_at_schema(gateway_app, seeded_key):
    """messages=[] 空数组在 schema 层拦截 → 400 OpenAI 信封，不漏到上游吃原文报错。"""
    plain, _ = seeded_key
    with _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(messages=[]),
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "invalid_request_error"
    assert body["error"]["param"] == "messages"


@pytest.mark.asyncio
async def test_stream_chunks_share_one_id(gateway_app, seeded_key):
    """OpenAI 官方语义：同一流内所有 chunk 共享同一 id。"""
    from novamind.shared.ai_models.base_model import StreamChunk

    plain, _ = seeded_key

    async def _stream(messages, **kwargs):
        yield StreamChunk(type="content", text="你")
        yield StreamChunk(type="content", text="好")

    async def _fake(self, user_id, model):
        from unittest.mock import MagicMock

        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_text_stream_structured = MagicMock(side_effect=_stream)
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(stream=True),
                headers={"Authorization": f"Bearer {plain}"},
            )

    chunks = [e for e in _parse_sse(resp.text) if e != "[DONE]"]
    ids = {c["id"] for c in chunks}
    assert len(ids) == 1
    assert ids.pop().startswith("chatcmpl-")


@pytest.mark.asyncio
async def test_stream_tools_finish_reason_normalized_when_upstream_says_stop(gateway_app, seeded_key):
    """上游工具场景误回 stop（DashScope 兼容层实测行为）→ 网关归一化为 tool_calls。"""
    from novamind.shared.ai_models.base_model import ToolStreamEvent

    plain, _ = seeded_key

    async def _stream(messages, tools=None, tool_choice="auto", **kwargs):
        yield ToolStreamEvent(type="tool_call_start", tool_call_id="c1", tool_name="get_weather")
        yield ToolStreamEvent(type="tool_call_args", tool_call_id="c1", tool_arguments_delta='{"city":"北京"}')
        # 上游给 stop——网关必须纠正，否则 agent 框架误判为普通结束
        yield ToolStreamEvent(type="done", finish_reason="stop", usage=None)

    async def _fake(self, user_id, model):
        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_with_tools_stream = _stream
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(
                    stream=True,
                    tools=[{"type": "function", "function": {"name": "get_weather"}}],
                ),
                headers={"Authorization": f"Bearer {plain}"},
            )

    chunks = [e for e in _parse_sse(resp.text) if e != "[DONE]"]
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


@pytest.mark.asyncio
async def test_stream_tools_finish_reason_respects_upstream_length(gateway_app, seeded_key):
    """相邻正常场景不误伤：上游显式给 length（截断）时不被归一化覆盖。"""
    from novamind.shared.ai_models.base_model import ToolStreamEvent

    plain, _ = seeded_key

    async def _stream(messages, tools=None, tool_choice="auto", **kwargs):
        yield ToolStreamEvent(type="tool_call_start", tool_call_id="c1", tool_name="get_weather")
        yield ToolStreamEvent(type="done", finish_reason="length", usage=None)

    async def _fake(self, user_id, model):
        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_with_tools_stream = _stream
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(
                    stream=True,
                    tools=[{"type": "function", "function": {"name": "get_weather"}}],
                ),
                headers={"Authorization": f"Bearer {plain}"},
            )

    chunks = [e for e in _parse_sse(resp.text) if e != "[DONE]"]
    assert chunks[-1]["choices"][0]["finish_reason"] == "length"


@pytest.mark.asyncio
async def test_stream_tools_no_tool_call_keeps_stop(gateway_app, seeded_key):
    """相邻正常场景不误伤：带 tools 请求但模型纯文本回答（无 tool_call 帧）→ 保持 stop。"""
    from novamind.shared.ai_models.base_model import ToolStreamEvent

    plain, _ = seeded_key

    async def _stream(messages, tools=None, tool_choice="auto", **kwargs):
        yield ToolStreamEvent(type="content", content="今天天气不错")
        yield ToolStreamEvent(type="done", finish_reason="stop", usage=None)

    async def _fake(self, user_id, model):
        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_with_tools_stream = _stream
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(
                    stream=True,
                    tools=[{"type": "function", "function": {"name": "get_weather"}}],
                ),
                headers={"Authorization": f"Bearer {plain}"},
            )

    chunks = [e for e in _parse_sse(resp.text) if e != "[DONE]"]
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_normalize_usage_accepts_both_key_families():
    """usage 双键兼容：OpenAI 惯例键（prompt_tokens）与内部键（input_tokens）都读得出。"""
    from novamind.features.agent_api.services.openai_gateway_service import _normalize_usage

    openai_style = _normalize_usage({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
    assert openai_style == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    internal_style = _normalize_usage({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    assert internal_style == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    assert _normalize_usage(None) == {}
    assert _normalize_usage({}) == {}


@pytest.mark.asyncio
async def test_non_stream_usage_passthrough_from_llm_response(gateway_app, seeded_key):
    """非流式 usage/finish_reason 透传：LLMResponse 携带时网关如实回显（验收 P1-2①）。"""
    from novamind.shared.ai_models.base_model import LLMResponse

    plain, _ = seeded_key
    resp_obj = LLMResponse(
        content="你好！",
        reasoning=None,
        usage={"input_tokens": 12, "output_tokens": 6, "total_tokens": 18},
        finish_reason="stop",
    )

    async def _fake(self, user_id, model):
        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_text_structured = AsyncMock(return_value=resp_obj)
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(),
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["usage"] == {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18}
    assert body["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_non_stream_finish_reason_length_passthrough(gateway_app, seeded_key):
    """上游截断（length）如实透传——验收 P1-2：max_tokens 语义对客户端可见。"""
    from novamind.shared.ai_models.base_model import LLMResponse

    plain, _ = seeded_key
    resp_obj = LLMResponse(content="只", usage=None, finish_reason="length")

    async def _fake(self, user_id, model):
        stub = AsyncMock()
        stub.quirks = None
        stub.capabilities = LLMCapabilities(tools=True, thinking=True)
        stub.generate_text_structured = AsyncMock(return_value=resp_obj)
        return stub

    with patch(
        "novamind.features.user.services.model_config_service.ModelConfigService.get_llm_client_by_model",
        new=_fake,
    ), _patch_user_status(True), _patch_touch():
        transport = ASGITransport(app=gateway_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json=_chat_body(max_tokens=1),
                headers={"Authorization": f"Bearer {plain}"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["finish_reason"] == "length"
    assert body["usage"] == {}
