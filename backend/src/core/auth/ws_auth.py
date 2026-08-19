"""WebSocket 认证（subprotocol 子协议传 JWT）。

浏览器 ``new WebSocket(url, ['bearer.<jwt>'])`` 把 JWT 放进 ``Sec-WebSocket-Protocol``
子协议头（不进 URL，避免代理日志/浏览器历史泄漏）。本模块在 WS 握手阶段解析
子协议、复用 ``core/auth`` 的 ``decode_access_token`` + ``is_user_blacklisted`` +
``UserStatusResolver`` 校验链，与 HTTP ``get_current_user`` 等价。

认证失败返回 ``(None, close_code)``，**不在本函数内 close**——由调用方先
``websocket.accept()`` 再 ``websocket.close(code=close_code)``。原因：accept 前
``websocket.close`` 会被 uvicorn 转成 HTTP 403 握手拒绝，close code 不作为 WS
close frame 传到客户端；accept 后 close 才能把 4401/4403 精准传给前端。
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
) -> tuple[Optional[dict], Optional[int]]:
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

    # 用户级黑名单（用户被软删除/停用时所有 Token 立即失效）
    if await is_user_blacklisted(claims.user_id, token_iat=claims.iat):
        return None, WS_CLOSE_UNAUTHENTICATED

    # 经端口取 DB 最新用户状态（core 不碰 user ORM）
    user = await resolver.get_user_for_auth(claims.user_id)
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