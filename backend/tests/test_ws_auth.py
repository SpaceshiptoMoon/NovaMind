"""WebSocket 认证单测：``novamind.core.auth.ws_auth.ws_authenticate``。

ws_authenticate 返回 ``(user, close_code)``，不在内部 close（由 handler accept 后
close 确保 code 精准传到客户端）。覆盖 4 条路径：
1. 有效 token + 活跃用户 → (user_dict, None)，不 close
2. 无 subprotocol token → (None, 4401)
3. 无效 token（解码失败）→ (None, 4401)
4. 用户已删除（is_deleted=True）→ (None, 4403)

JWT 解码走真实 ``decode_access_token`` —— 通过 monkeypatch ``token.get_config``
注入已知 secret_key，避免依赖 YAML 配置文件。黑名单查询 ``is_user_blacklisted``
经 monkeypatch 短路为 False，避免 Redis。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from novamind.core.auth.ws_auth import ws_authenticate

pytestmark = pytest.mark.unit

# 与 fake_config 注入的 secret_key 一致，供 _make_jwt 签发可被 decode_access_token 验通过的 JWT
_TEST_SECRET = "test-secret-key-for-ws-auth"
_TEST_ALGORITHM = "HS256"


@pytest.fixture
def fake_config(monkeypatch):
    """注入已知 secret_key 的 config，让真实 decode_access_token 能解 _make_jwt 签的 token。"""

    class _Security:
        secret_key = _TEST_SECRET
        algorithm = _TEST_ALGORITHM
        access_token_expire_minutes = 30

    class _Config:
        security = _Security()

    import novamind.core.auth.token as token_mod

    monkeypatch.setattr(token_mod, "get_config", lambda: _Config())
    return _Config()


@pytest.fixture
def no_blacklist(monkeypatch):
    """短路 is_user_blacklisted（避免 Redis），默认返回 False（未拉黑）。"""
    import novamind.core.auth.ws_auth as ws_mod

    monkeypatch.setattr(ws_mod, "is_user_blacklisted", AsyncMock(return_value=False))


class FakeWS:
    """最小 WebSocket mock：只暴露 ws_authenticate 用到的 headers + close。

    ws_authenticate 不再内部 close，close 仅用于断言「未被调用」。
    """

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers
        self.close = AsyncMock()


def _make_jwt(
    user_id: int = 1,
    username: str = "tester",
    email: str = "tester@example.com",
    is_admin: bool = False,
    status: int = 1,
) -> str:
    """签发与 AuthService.create_access_token 字段一致的 access token（exp 远未来）。"""
    payload = {
        "sub": username,
        "user_id": user_id,
        "username": username,
        "email": email,
        "is_admin": is_admin,
        "status": status,
        "type": "access",
        "jti": "test-jti",
        "iat": 1000,
        "exp": 9999999999,
    }
    return jwt.encode(payload, _TEST_SECRET, algorithm=_TEST_ALGORITHM)


def _make_resolver(user: dict | None) -> SimpleNamespace:
    return SimpleNamespace(get_user_for_auth=AsyncMock(return_value=user))


# ===== 用例 1：有效 token + 活跃用户 =====


@pytest.mark.asyncio
async def test_valid_token_active_user(fake_config, no_blacklist):
    token = _make_jwt(user_id=1, username="tester", is_admin=False)
    ws = FakeWS({"sec-websocket-protocol": f"bearer.{token}"})
    resolver = _make_resolver(
        {
            "id": 1,
            "username": "tester",
            "email": "tester@example.com",
            "is_admin": False,
            "status": 1,
            "is_active": True,
            "is_deleted": False,
        }
    )

    user, close_code = await ws_authenticate(ws, resolver)

    assert close_code is None
    assert user is not None
    assert user["id"] == 1
    assert user["username"] == "tester"
    assert user["email"] == "tester@example.com"
    assert user["is_admin"] is False
    assert user["status"] == 1
    assert user["jti"] == "test-jti"
    ws.close.assert_not_called()  # 不在内部 close，由 handler close
    resolver.get_user_for_auth.assert_awaited_once_with(1)


# ===== 用例 2：无 subprotocol token =====


@pytest.mark.asyncio
async def test_no_subprotocol_token(fake_config, no_blacklist):
    ws = FakeWS({})  # 无 sec-websocket-protocol
    resolver = _make_resolver(None)

    user, close_code = await ws_authenticate(ws, resolver)

    assert user is None
    assert close_code == 4401
    ws.close.assert_not_called()  # 不在内部 close
    resolver.get_user_for_auth.assert_not_called()


# ===== 用例 3：无效 token =====


@pytest.mark.asyncio
async def test_invalid_token(fake_config, no_blacklist):
    ws = FakeWS({"sec-websocket-protocol": "bearer.invalid-jwt"})
    resolver = _make_resolver(None)

    user, close_code = await ws_authenticate(ws, resolver)

    assert user is None
    assert close_code == 4401
    ws.close.assert_not_called()
    resolver.get_user_for_auth.assert_not_called()


# ===== 用例 4：用户已删除 =====


@pytest.mark.asyncio
async def test_user_deleted(fake_config, no_blacklist):
    token = _make_jwt(user_id=2, username="ghost")
    ws = FakeWS({"sec-websocket-protocol": f"bearer.{token}"})
    resolver = _make_resolver(
        {
            "id": 2,
            "username": "ghost",
            "email": "ghost@example.com",
            "is_admin": False,
            "status": 0,
            "is_active": False,
            "is_deleted": True,
        }
    )

    user, close_code = await ws_authenticate(ws, resolver)

    assert user is None
    assert close_code == 4403
    ws.close.assert_not_called()