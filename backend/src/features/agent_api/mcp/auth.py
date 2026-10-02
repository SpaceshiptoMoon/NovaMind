"""MCP tool 内鉴权 helper：按次校验 X-API-Key（吊销即时失效语义的保证）。

不能依赖「会话建立时校验」：stateless 下无会话；且 contextvar 跨 ASGI→tool
（memory stream 跨 task 派发）不保证传播——starlette Request 对象经
request_context 传递是唯一可靠通道（已核实 StreamableHTTPServerTransport
把 Request 塞进 ServerMessageMetadata.request_context）。
"""
from __future__ import annotations

from mcp.server.fastmcp import Context

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.agent_api.exceptions import InvalidApiKeyError
from novamind.features.agent_api.services.api_key_service import ApiKeyAuthContext

logger = get_logger(__name__)


async def require_api_key(ctx: Context) -> ApiKeyAuthContext:
    """从 MCP Context 提取 X-API-Key 并按次鉴权。

    Raises:
        ToolError: key 缺失/无效/已吊销/用户禁用——消息面向 LLM 简短说明。
    """
    request = ctx.request_context.request
    if request is None:
        raise ToolError("缺少请求上下文，无法鉴权")
    plain_key = request.headers.get("x-api-key")
    if not plain_key:
        raise ToolError("缺少 X-API-Key header——请在 MCP 客户端配置中提供有效凭证")

    from novamind.core.database.database import get_db_session
    from novamind.features.agent_api.services.api_key_service import ApiKeyService

    try:
        async with get_db_session() as session:
            service = ApiKeyService(session)
            auth = await service.authenticate(plain_key)
            await session.commit()
            return auth
    except InvalidApiKeyError:
        raise ToolError("API key 无效或已吊销——请在 NovaMind 重新生成")
    except Exception as e:
        logger.warning("MCP tool 鉴权异常（转 ToolError）", error=str(e))
        raise ToolError("鉴权服务暂时不可用，请稍后重试")


# ToolError 从 mcp SDK 导出再导出，调用方统一从这里 import
from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402
