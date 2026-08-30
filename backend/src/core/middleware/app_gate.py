"""AppGateMiddleware：应用级权限门禁（纯 ASGI 中间件）。

三级权限模型的应用层执行点——管理员可禁用普通用户的具体应用
（qa/agent/skill/app/clawmate），被禁应用的 HTTP 与 WebSocket 请求在此拦截。

为什么是纯 ASGI 中间件而不是 router 级 ``dependencies``：agent/clawmate/qa
的 WebSocket 端点用 subprotocol ``bearer.<jwt>`` 认证（浏览器 WS 无法带
Authorization 头），FastAPI router 级依赖里的 ``HTTPBearer`` 会拒绝 WS 握手；
纯 ASGI 中间件按 ``scope["type"]`` 分流，http/websocket 各自提取 token，
单一收口点覆盖两个传输层，五个 feature 的路由文件零改动。

安全语义：门禁是产品可见性控制，不是安全边界——认证/撤销检查仍在端点依赖
链（get_current_user / ws_authenticate），空间内容权限仍在 space_members 表。
检查异常时 fail-open 放行并记 error 日志。admin 角色按 JWT claims 直通
（claims 有 ≤30 分钟陈旧性：刚降级的管理员最长残留一个 access token 周期；
撤销类检查不受影响，仍由端点认证层强制）。
"""
from __future__ import annotations

import json
from typing import Optional

from novamind.core.authorization.app_codes import match_app_code
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 门禁拒绝 close code（与 ws_authenticate 的 4403 语义对齐：认证通过但状态/权限不允许）
WS_CLOSE_APP_DENIED = 4403

_BEARER_PREFIX = "bearer."


class AppGateMiddleware:
    """应用门禁中间件（挂载于 app_factory._add_middleware，CORS 内层）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        app_code = match_app_code(path)
        if app_code is None:
            await self.app(scope, receive, send)
            return

        # CORS 预检直通
        if scope["type"] == "http" and scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        user_id: Optional[int] = None
        try:
            user_id, denied = await self._check(scope, app_code)
        except Exception as e:  # fail-open：门禁是可见性控制，故障不放行为拒绝
            logger.error(
                "应用门禁检查异常，放行请求",
                path=path,
                app_code=app_code,
                error=str(e),
            )
            denied = False

        if not denied:
            await self.app(scope, receive, send)
            return

        logger.info("应用访问被拒绝", path=path, app_code=app_code, user_id=user_id)
        if scope["type"] == "http":
            await self._send_http_forbidden(send)
        else:
            await self._close_ws_denied(send)

    # ==================== 内部 ====================

    async def _check(self, scope, app_code: str) -> tuple[Optional[int], bool]:
        """返回 (user_id, denied)。无 token/解码失败→(None, False)，
        由端点认证层自行 401/4401，中间件不重复报错。"""
        from novamind.core.auth.token import decode_access_token

        token = self._extract_token(scope)
        if not token:
            return None, False
        claims = decode_access_token(token)
        if not claims or not claims.user_id:
            return None, False
        if claims.role_code == "admin":
            return claims.user_id, False

        from novamind.core.database.database import get_db_session
        from novamind.features.user.services.app_access_service import AppAccessService

        redis_client = None
        try:
            from novamind.shared.storage.client_factory import ClientFactory

            redis_client = await ClientFactory.get_redis_client()
        except Exception:
            redis_client = None

        async with get_db_session() as db:
            svc = AppAccessService(db, redis_client)
            denied = await svc.is_app_disabled(claims.user_id, app_code)
        return claims.user_id, denied

    @staticmethod
    def _extract_token(scope) -> Optional[str]:
        """http 取 Authorization 头；websocket 取 sec-websocket-protocol 的 bearer. 前缀。"""
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        if scope["type"] == "http":
            auth = headers.get("authorization", "")
            if auth.startswith("Bearer "):
                return auth[7:]
            return None
        sub = headers.get("sec-websocket-protocol", "")
        for piece in sub.split(","):
            piece = piece.strip()
            if piece.lower().startswith(_BEARER_PREFIX):
                return piece[len(_BEARER_PREFIX):]
        return None

    @staticmethod
    async def _send_http_forbidden(send) -> None:
        """发 403 JSON（错误信封与 BaseAPIError handler 格式一致）。"""
        body = json.dumps(
            {
                "code": "APP_ACCESS_DENIED",
                "message": "该应用已被管理员禁用",
                "details": None,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _close_ws_denied(send) -> None:
        """WS 拒绝：发 websocket.close 帧拒绝握手（uvicorn 转成 HTTP 403）。

        不先 accept——门禁拒绝属握手期拦截，客户端收到的是连接失败而非
        业务 close code（与 ws_authenticate 的 accept 后 close 不同：那是认证
        链路需要精准 close code，这里是硬拒绝）。
        """
        await send({"type": "websocket.close", "code": WS_CLOSE_APP_DENIED, "reason": "app disabled"})


__all__ = ["AppGateMiddleware", "WS_CLOSE_APP_DENIED"]
