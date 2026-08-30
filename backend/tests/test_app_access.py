"""应用级权限门禁测试：前缀匹配、中间件分流、deny-list 服务语义。

中间件测试不经真实 Redis/DB——monkeypatch decode_access_token 与
AppAccessService.is_app_disabled，纯验证分流逻辑；服务测试用 tmp_db。
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy import select

from novamind.core.authorization.app_codes import AppCode, match_app_code
from novamind.features.user.models.user_disabled_app import UserDisabledApp
from novamind.features.user.services.app_access_service import AppAccessService


# ==================== 前缀段边界匹配 ====================


class TestMatchAppCode:
    def test_exact_and_subpath_match(self):
        assert match_app_code("/api/v1/agent") == "agent"
        assert match_app_code("/api/v1/agent/1/chat") == "agent"
        assert match_app_code("/api/v1/qa/sessions") == "qa"
        assert match_app_code("/api/v1/skills") == "skill"
        assert match_app_code("/api/v1/apps/resume") == "app"
        assert match_app_code("/api/v1/clawmate/ws") == "clawmate"
        assert match_app_code("/api/v1/ai-chat/history") == "qa"

    def test_segment_boundary_not_prefix(self):
        # 段边界匹配：/api/v1/agentx 不能误命中 agent
        assert match_app_code("/api/v1/agentx") is None
        assert match_app_code("/api/v1/skillsx") is None
        assert match_app_code("/api/v1/appsx/1") is None

    def test_ungated_paths_pass(self):
        # 知识空间/深研究/测评/通知/用户管理不进应用门禁
        assert match_app_code("/api/v1/spaces/1/knowledge-bases") is None
        assert match_app_code("/api/v1/spaces/1/deep-research") is None
        assert match_app_code("/api/v1/notifications") is None
        assert match_app_code("/api/v1/user/users/me/permissions") is None
        assert match_app_code("/docs") is None


# ==================== 中间件分流 ====================


def _http_scope(path: str, token: str | None = None) -> dict:
    headers = [(b"content-type", b"application/json")]
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "query_string": b"",
    }


def _ws_scope(path: str, token: str | None = None) -> dict:
    headers = []
    if token:
        headers.append((b"sec-websocket-protocol", f"bearer.{token}".encode()))
    return {"type": "websocket", "path": path, "headers": headers}


class _Recorder:
    """记录下游 app 是否被调用与 send 的消息。"""

    def __init__(self):
        self.called = False
        self.sent: list[dict] = []

    async def downstream(self, scope, receive, send):
        self.called = True

    async def send(self, message):
        self.sent.append(message)


class _FakeClaims:
    def __init__(self, user_id: int, role_code: str):
        self.user_id = user_id
        self.role_code = role_code


async def _noop_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.mark.asyncio
async def test_gate_denied_http_403(monkeypatch):
    """被禁应用的 HTTP 请求 → 403 APP_ACCESS_DENIED，不进下游。"""
    from novamind.core.middleware.app_gate import AppGateMiddleware

    rec = _Recorder()
    mw = AppGateMiddleware(rec.downstream)

    class Claims:
        user_id = 7
        role_code = "viewer"

    def fake_decode(token):
        return Claims()

    async def fake_is_disabled(self, uid, code):
        return True

    def fake_get_db_session():
        class _CM:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *a):
                return False

        return _CM()

    import novamind.core.auth.token as token_mod

    monkeypatch.setattr(token_mod, "decode_access_token", fake_decode)
    monkeypatch.setattr(AppAccessService, "is_app_disabled", fake_is_disabled)
    import novamind.core.database.database as db_mod

    monkeypatch.setattr(db_mod, "get_db_session", fake_get_db_session)
    import novamind.shared.storage.client_factory as cf_mod

    async def fail_redis(cls):
        raise RuntimeError("no redis in test")

    monkeypatch.setattr(cf_mod.ClientFactory, "get_redis_client", fail_redis)

    await mw(_http_scope("/api/v1/agent/5", token="t"), _noop_receive, rec.send)

    assert not rec.called
    start = next(m for m in rec.sent if m["type"] == "http.response.start")
    assert start["status"] == 403
    body = next(m for m in rec.sent if m["type"] == "http.response.body")
    payload = json.loads(body["body"])
    assert payload["code"] == "APP_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_gate_admin_bypass_without_db(monkeypatch):
    """admin claims 直通——不触发 DB/Redis（role_code 短路在查库之前）。"""
    from novamind.core.middleware.app_gate import AppGateMiddleware

    rec = _Recorder()
    mw = AppGateMiddleware(rec.downstream)

    class Claims:
        user_id = 1
        role_code = "admin"

    def fake_decode(token):
        return Claims()

    import novamind.core.auth.token as token_mod

    monkeypatch.setattr(token_mod, "decode_access_token", fake_decode)

    # 若尝试查库则报错（证明 admin 分支未走到）
    import novamind.core.database.database as db_mod

    async def fail_session():
        raise AssertionError("admin should bypass DB check")

    monkeypatch.setattr(db_mod, "get_db_session", fail_session)

    await mw(_http_scope("/api/v1/agent/5", token="t"), _noop_receive, rec.send)
    assert rec.called


@pytest.mark.asyncio
async def test_gate_no_token_passes_through():
    """无 token 直通（端点认证层自会 401）。"""
    from novamind.core.middleware.app_gate import AppGateMiddleware

    rec = _Recorder()
    mw = AppGateMiddleware(rec.downstream)
    await mw(_http_scope("/api/v1/agent/5"), _noop_receive, rec.send)
    assert rec.called


@pytest.mark.asyncio
async def test_gate_fail_open_on_error(monkeypatch):
    """查库异常 → fail-open 放行 + 不影响请求。"""
    from novamind.core.middleware.app_gate import AppGateMiddleware

    rec = _Recorder()
    mw = AppGateMiddleware(rec.downstream)

    class Claims:
        user_id = 7
        role_code = "viewer"

    def fake_decode(token):
        return Claims()

    import novamind.core.auth.token as token_mod

    monkeypatch.setattr(token_mod, "decode_access_token", fake_decode)

    import novamind.core.database.database as db_mod

    async def boom_session():
        raise RuntimeError("db down")

    monkeypatch.setattr(db_mod, "get_db_session", boom_session)
    import novamind.shared.storage.client_factory as cf_mod

    async def fail_redis(cls):
        raise RuntimeError("no redis")

    monkeypatch.setattr(cf_mod.ClientFactory, "get_redis_client", fail_redis)

    await mw(_http_scope("/api/v1/skills"), _noop_receive, rec.send)
    assert rec.called  # fail-open


@pytest.mark.asyncio
async def test_gate_ws_denied(monkeypatch):
    """被禁应用的 WS 握手被拒（websocket.close，不进下游）。"""
    from novamind.core.middleware.app_gate import AppGateMiddleware

    rec = _Recorder()
    mw = AppGateMiddleware(rec.downstream)

    class Claims:
        user_id = 7
        role_code = "viewer"

    def fake_decode(token):
        return Claims()

    async def fake_is_disabled(self, uid, code):
        return True

    def fake_get_db_session():
        class _CM:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *a):
                return False

        return _CM()

    import novamind.core.auth.token as token_mod

    monkeypatch.setattr(token_mod, "decode_access_token", fake_decode)
    monkeypatch.setattr(AppAccessService, "is_app_disabled", fake_is_disabled)
    import novamind.core.database.database as db_mod

    monkeypatch.setattr(db_mod, "get_db_session", fake_get_db_session)
    import novamind.shared.storage.client_factory as cf_mod

    async def fail_redis(cls):
        raise RuntimeError("no redis")

    monkeypatch.setattr(cf_mod.ClientFactory, "get_redis_client", fail_redis)

    await mw(_ws_scope("/api/v1/agent/1/ws", token="t"), _noop_receive, rec.send)

    assert not rec.called
    close = next(m for m in rec.sent if m["type"] == "websocket.close")
    assert close["code"] == 4403


@pytest.mark.asyncio
async def test_gate_options_preflight_passes():
    """CORS 预检直通。"""
    from novamind.core.middleware.app_gate import AppGateMiddleware

    rec = _Recorder()
    mw = AppGateMiddleware(rec.downstream)
    scope = _http_scope("/api/v1/agent")
    scope["method"] = "OPTIONS"
    await mw(scope, _noop_receive, rec.send)
    assert rec.called


# ==================== AppAccessService deny-list 语义 ====================


@pytest_asyncio.fixture
async def app_db(tmp_db):
    """tmp_db 基础上定向建 user_disabled_apps 表。"""
    from novamind.core.database.base import Base

    engine = tmp_db.bind
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=[UserDisabledApp.__table__])
        )
    return tmp_db


@pytest.mark.asyncio
async def test_default_all_enabled(app_db):
    """无记录 = 全部可用（默认全开放语义）。"""
    svc = AppAccessService(app_db, redis_client=None)
    assert await svc.get_disabled_apps(42) == set()
    assert await svc.is_app_disabled(42, "agent") is False


@pytest.mark.asyncio
async def test_set_and_replace(app_db):
    """全量替换语义：先禁两个，再替换为一个。"""
    svc = AppAccessService(app_db, redis_client=None)
    await svc.set_disabled_apps(42, {"agent", "skill"}, operator_id=1)
    assert await svc.get_disabled_apps(42) == {"agent", "skill"}
    assert await svc.is_app_disabled(42, "agent") is True
    assert await svc.is_app_disabled(42, "qa") is False

    await svc.set_disabled_apps(42, {"qa"})
    assert await svc.get_disabled_apps(42) == {"qa"}

    # 底层行数：替换后只有 1 行，无残留（全量替换语义：旧行删除，新行无 operator）
    rows = (await app_db.execute(select(UserDisabledApp))).scalars().all()
    assert len(rows) == 1
    assert rows[0].app_code == "qa"

    # 带 operator 的替换保留操作人
    await svc.set_disabled_apps(42, {"qa"}, operator_id=9)
    await app_db.flush()
    rows = (await app_db.execute(select(UserDisabledApp))).scalars().all()
    assert rows[0].created_by == 9


@pytest.mark.asyncio
async def test_apps_isolated_per_user(app_db):
    """应用相互隔离 + 用户相互隔离：A 被禁不影响 B。"""
    svc = AppAccessService(app_db, redis_client=None)
    await svc.set_disabled_apps(1, {"agent"})
    assert await svc.is_app_disabled(1, "agent") is True
    assert await svc.is_app_disabled(2, "agent") is False
    assert await svc.is_app_disabled(1, "qa") is False
