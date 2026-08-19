"""WebSocket 认证（subprotocol 子协议传 JWT）。

浏览器 ``new WebSocket(url, ['bearer.<jwt>'])`` 把 JWT 放进 ``Sec-WebSocket-Protocol``
子协议头（不进 URL，避免代理日志/浏览器历史泄漏）。本模块在 WS 握手阶段解析
子协议、复用 ``core/auth`` 的 ``decode_access_token`` + ``is_user_blacklisted`` +
``UserStatusResolver`` 校验链，与 HTTP ``get_current_user`` 等价。

认证失败 ``await websocket.close(code=4401/4403)``（Starlette 在 accept 前 close
会向客户端回 403）；成功返回 user dict，由调用方 ``websocket.accept(subprotocol=...)``。
"""
from __future__ import annotations

from typing import Optional

from fastapi import WebSocket

from novamind.core.auth.blacklist import is_user_blacklisted
from novamind.core.auth.ports import UserStatusResolver
from novamind.core.auth.token import decode_access_token

_BEARER_PREFIX = "bearer."

# WS 认证失败 close code（4401 未认证 / 4403 状态不允许）
WS_CLOSE_UNAUTHENTICATED = 4401
WS_CLOSE_FORBIDDEN = 4403


def ws_extract_token(websocket: WebSocket) -> Optional[str]:
    """从 ``Sec-WebSocket-Protocol`` 子协议解析 bearer token。

    客户端可传多个子协议（逗号分隔），取首个 ``bearer.`` 前缀的。
    """
    sub = websocket.headers.get("sec-websocket-protocol") or ""
    for piece in sub.split(","):
        piece = piece.strip()
        if piece.lower().startswith(_BEARER_PREFIX):
            return piece[len(_BEARER_PREFIX):]
    return None


async def ws_authenticate(
    websocket: WebSocket, resolver: UserStatusResolver
) -> Optional[dict]:
    """WS 握手认证：subprotocol JWT → 黑名单 → 用户状态。

    失败时 ``await websocket.close(...)`` 并返回 ``None``；成功返回 user dict
    （字段对齐 HTTP ``get_current_user``）。调用方拿到非 None 后再 ``accept``。
    """
    token = ws_extract_token(websocket)
    claims = decode_access_token(token) if token else None
    if not claims or not claims.user_id:
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
        return None

    # 用户级黑名单（用户被软删除/停用时所有 Token 立即失效）
    if await is_user_blacklisted(claims.user_id, token_iat=claims.iat):
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
        return None

    # 经端口取 DB 最新用户状态（core 不碰 user ORM）
    user = await resolver.get_user_for_auth(claims.user_id)
    if not user:
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
        return None
    if user.get("is_deleted"):
        await websocket.close(code=WS_CLOSE_FORBIDDEN)
        return None
    if not user.get("is_active") and not user.get("is_admin"):
        await websocket.close(code=WS_CLOSE_FORBIDDEN)
        return None

    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "is_admin": user["is_admin"],
        "status": user.get("status"),
        "jti": claims.jti,
    }


__all__ = [
    "ws_extract_token",
    "ws_authenticate",
    "WS_CLOSE_UNAUTHENTICATED",
    "WS_CLOSE_FORBIDDEN",
]