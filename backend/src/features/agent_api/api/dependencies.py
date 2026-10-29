"""Agent API 依赖：X-API-Key 鉴权通道与 key 服务装配。

get_api_key_user 返回与 core/auth.get_current_user 兼容的用户 dict——
后续路由把 Depends(get_current_user) 换成 Depends(get_api_key_user)
即可获得 key 通道（本期不改动现有路由，仅提供能力）。
"""
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, Request
from novamind.core.database.database import get_db
from novamind.features.agent_api.exceptions import GatewayAuthError, InvalidApiKeyError
from novamind.features.agent_api.services.api_key_service import ApiKeyService
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from novamind.features.agent_api.services.openai_gateway_service import OpenAiGatewayService

# get_current_user 用户 dict 中 key 通道不适用/恒定的字段：
# jti=None（API key 无 JWT 会话概念，黑名单机制不适用——吊销即时失效由
# 鉴权路径实时查库保证）；must_change_password=False（key 通道不拦截改密门禁，
# 管理性操作走 JWT）。
_API_KEY_USER_DEFAULTS = {"jti": None, "must_change_password": False}


async def get_api_key_service(db: AsyncSession = Depends(get_db)) -> ApiKeyService:
    """装配 key 服务（请求级会话）。"""
    return ApiKeyService(db)



async def get_gateway_service(
    db: AsyncSession = Depends(get_db),
) -> "OpenAiGatewayService":
    """装配 OpenAI 网关服务（请求级会话）。"""
    from novamind.features.agent_api.services.openai_gateway_service import OpenAiGatewayService

    return OpenAiGatewayService(db)


async def get_api_key_user(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    service: ApiKeyService = Depends(get_api_key_service),
) -> dict:
    """X-API-Key 鉴权：校验通过返回与 get_current_user 兼容的用户 dict。

    失败统一 InvalidApiKeyError(401)——缺失/无效/已吊销/用户禁用不区分原因
    （防探测）。成功写 request.state.user_id（限流键对齐）。
    """
    if not x_api_key:
        raise InvalidApiKeyError("缺少 X-API-Key header")

    auth = await service.authenticate(x_api_key)
    user = {**auth.user, **_API_KEY_USER_DEFAULTS}
    request.state.user_id = auth.user_id
    return user


async def get_gateway_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    service: ApiKeyService = Depends(get_api_key_service),
) -> dict:
    """网关鉴权：Authorization: Bearer 优先（OpenAI SDK 惯例），回落 X-API-Key。

    失败抛 GatewayAuthError（经专属 handler 输出 OpenAI 错误格式，区别于
    管理端点的统一信封）；成功写 request.state.user_id（限流键对齐）。
    """
    plain_key: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        plain_key = authorization[7:].strip()
    if not plain_key:
        plain_key = x_api_key
    if not plain_key:
        raise GatewayAuthError(
            "缺失鉴权凭证：请在 Authorization: Bearer <key> 或 X-API-Key header 提供 API key"
        )

    try:
        auth = await service.authenticate(plain_key)
    except InvalidApiKeyError as e:
        raise GatewayAuthError() from e
    user = {**auth.user, **_API_KEY_USER_DEFAULTS}
    request.state.user_id = auth.user_id
    return user
