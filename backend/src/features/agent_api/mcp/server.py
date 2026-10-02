"""NovaMind MCP server（agent_api 批次 2）：把知识库能力按 MCP 标准暴露给外部 agent。

传输：streamable_http（stateless + JSON 响应）——无会话状态、每 POST 独立响应、
代理最稳、自家 McpClientManager 兼容。

挂载方式（绕 mount 404 坑）：FastMCP.streamable_http_app() 的内部 Route path
固定 /mcp，直接 mount 会变 /mcp/mcp 且空路径不匹配——改为自定义纯 ASGI 端点
直连 session_manager.handle_request（它按 method/headers 分发，不感知 path），
端点内先做 X-API-Key 门禁（失败手工 send 401 JSON，绝不进 MCP 协议层）。
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

MCP_SERVER_NAME = "novamind"


def build_mcp_server() -> FastMCP:
    """构造 MCP server 实例并注册 kb tools。"""
    mcp: FastMCP = FastMCP(
        name=MCP_SERVER_NAME,
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool(
        name="kb_search",
        description=(
            "在 NovaMind 知识库中检索与 query 相关的内容片段。"
            "返回带 rank/score/snippet 的片段列表（snippet 序号即引用编号）。"
            "space_id/kb_id 缺省时自动解析（多空间会返回候选清单）。"
        ),
    )
    async def kb_search(
        query: str,
        space_id: int | None = None,
        kb_id: int | None = None,
        top_k: int = 5,
        ctx: Context = None,
    ) -> str:
        from novamind.features.agent_api.mcp.auth import require_api_key
        from novamind.features.agent_api.services.mcp_kb_service import McpKbService

        auth = await require_api_key(ctx)
        async with _new_session() as session:
            service = McpKbService(session)
            return await service.search(
                user_id=auth.user_id, query=query,
                space_id=space_id, kb_id=kb_id, top_k=top_k,
                with_answer=False,
            )

    @mcp.tool(
        name="kb_ask",
        description=(
            "基于 NovaMind 知识库回答问题：检索相关片段并生成带 [Source N] 引用的答案"
            "（N 与输出 results 的 rank 对齐，可回溯原文）。适合事实型问题；"
            "检索无结果时 answer 为 null。"
        ),
    )
    async def kb_ask(
        query: str,
        space_id: int | None = None,
        kb_id: int | None = None,
        top_k: int = 5,
        ctx: Context = None,
    ) -> str:
        from novamind.features.agent_api.mcp.auth import require_api_key
        from novamind.features.agent_api.services.mcp_kb_service import McpKbService

        auth = await require_api_key(ctx)
        async with _new_session() as session:
            service = McpKbService(session)
            return await service.search(
                user_id=auth.user_id, query=query,
                space_id=space_id, kb_id=kb_id, top_k=top_k,
                with_answer=True,
            )

    return mcp


def _new_session():
    """tool 内独立短会话（每次调用独立，鉴权与检索各自开——互不绑事务命运）。"""
    from contextlib import asynccontextmanager

    from novamind.core.database.database import get_db_session

    return get_db_session()


class McpAsgiEndpoint:
    """纯 ASGI 端点：X-API-Key 门禁 + 委托 session_manager.handle_request。

    每个 HTTP 请求（initialize/tools/list/tools/call）都先过鉴权——
    无钥方连 tools/list 都拿不到；失败统一 401 JSON 信封
    （与 BaseAPIError 响应同构：{error: {code, message}}）。
    """

    # starlette Route 构造时读 endpoint.__name__ 作为路由名（纯 ASGI 类需显式提供）
    __name__ = "mcp_asgi_endpoint"

    def __init__(self, session_manager: Any):
        self._session_manager = session_manager

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._send_json(send, 400, "MCP 端点仅接受 HTTP 请求")
            return

        # 提取 X-API-Key（ASGI headers 是小写键的二元组列表）
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        plain_key = headers.get("x-api-key")
        if not plain_key:
            await self._send_json(send, 401, "缺少 X-API-Key header", code="INVALID_API_KEY")
            return

        from novamind.features.agent_api.exceptions import InvalidApiKeyError
        from novamind.features.agent_api.services.api_key_service import ApiKeyService
        from novamind.core.database.database import get_db_session

        try:
            async with get_db_session() as session:
                service = ApiKeyService(session)
                auth = await service.authenticate(plain_key)
                await session.commit()
            logger.debug(
                "MCP 请求鉴权通过",
                user_id=auth.user_id, key_id=auth.key_id, path=scope.get("path"),
            )
        except InvalidApiKeyError:
            await self._send_json(send, 401, "API key 无效或已吊销", code="INVALID_API_KEY")
            return
        except Exception as e:
            logger.warning("MCP 端点鉴权异常", error=str(e))
            await self._send_json(send, 401, "鉴权失败", code="INVALID_API_KEY")
            return

        # 通过 → 委托 session manager（POST/GET/DELETE 分发在其内部）
        await self._session_manager.handle_request(scope, receive, send)

    async def _send_json(self, send, status: int, message: str, code: str = "ERROR") -> None:
        """手工发送 401/400 JSON 信封（不进 MCP 协议层）。"""
        body = json.dumps(
            {"error": {"code": code, "message": message}},
            ensure_ascii=False,
        ).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
