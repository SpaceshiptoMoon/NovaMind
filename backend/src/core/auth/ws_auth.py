"""WebSocket 认证（subprotocol 子协议传 JWT）。

认证失败返回 (None, close_code) 且不在本函数内 close；调用方必须先 accept() 再 close(code)。
accept 前 close 会被 uvicorn 转成 HTTP 403，close code 无法作为 WS close frame 传到前端。
"""
from __future__ import annotations

from fastapi import WebSocket
from novamind.core.auth.blacklist import is_token_revoked, is_user_blacklisted
from novamind.core.auth.token import decode_access_token
from novamind.features.user.services.user_service import UserService

_BEARER_PREFIX = "bearer."

# WS 认证失败 close code（4401 未认证 / 4403 状态不允许）
WS_CLOSE_UNAUTHENTICATED = 4401
WS_CLOSE_FORBIDDEN = 4403


def ws_extract_token(websocket: WebSocket) -> str | None:
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
    websocket: WebSocket, resolver: UserService
) -> tuple[dict | None, int | None]:
    """WS 握手认证：subprotocol JWT → 黑名单 → 用户状态。

    返回 ``(user, close_code)``：
    - 成功：``(user_dict, None)``（user dict 字段对齐 HTTP ``get_current_user``）
    - 失败：``(None, close_code)``（4401 未认证 / 4403 状态不允许）

    **不调 ``websocket.close``**——由调用方 ``accept`` 后 ``close(close_code)``
    确保 close code 作为 WS close frame 传到客户端。
    """
    token = ws_extract_token(websocket)
    claims = decode_access_token(token) if token else None
    if not claims or not claims.user_id:
        return None, WS_CLOSE_UNAUTHENTICATED

    # token 级黑名单（登出/刷新轮换后该 jti 立即失效）
    if claims.jti and await is_token_revoked(claims.jti):
        return None, WS_CLOSE_UNAUTHENTICATED

    # 用户级黑名单（用户被软删除/停用时所有 Token 立即失效）
    if await is_user_blacklisted(claims.user_id, token_iat=claims.iat):
        return None, WS_CLOSE_UNAUTHENTICATED

    # 经端口取 DB 最新用户状态（core 不碰 user ORM）
    user = await resolver.get_auth_status(claims.user_id)
    if not user:
        return None, WS_CLOSE_UNAUTHENTICATED
    if user.get("is_deleted"):
        return None, WS_CLOSE_FORBIDDEN
    if not user.get("is_active") and not user.get("is_admin"):
        return None, WS_CLOSE_FORBIDDEN

    return (
        {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "is_admin": user["is_admin"],
            "status": user.get("status"),
            "jti": claims.jti,
        },
        None,
    )


__all__ = [
    "ws_extract_token",
    "ws_authenticate",
    "WS_CLOSE_UNAUTHENTICATED",
    "WS_CLOSE_FORBIDDEN",
]