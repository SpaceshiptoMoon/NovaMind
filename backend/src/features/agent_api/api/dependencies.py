"""Agent API 依赖：X-API-Key 鉴权通道与 key 服务装配。

get_api_key_user 返回与 core/auth.get_current_user 兼容的用户 dict——
后续路由把 Depends(get_current_user) 换成 Depends(get_api_key_user)
即可获得 key 通道（本期不改动现有路由，仅提供能力）。
"""
from typing import Annotated

from fastapi import Depends, Header, Request
from novamind.core.database.database import get_db
from novamind.features.agent_api.exceptions import InvalidApiKeyError
from novamind.features.agent_api.services.api_key_service import ApiKeyService
from sqlalchemy.ext.asyncio import AsyncSession

# get_current_user 用户 dict 中 key 通道不适用/恒定的字段：
# jti=None（API key 无 JWT 会话概念，黑名单机制不适用——吊销即时失效由
# 鉴权路径实时查库保证）；must_change_password=False（key 通道不拦截改密门禁，
# 管理性操作走 JWT）。
_API_KEY_USER_DEFAULTS = {"jti": None, "must_change_password": False}


async def get_api_key_service(db: AsyncSession = Depends(get_db)) -> ApiKeyService:
    """装配 key 服务（请求级会话）。"""
    return ApiKeyService(db)


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
