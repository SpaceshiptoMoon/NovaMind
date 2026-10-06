"""OpenAI 兼容网关路由：/v1/models 与 /v1/chat/completions（外部 OpenAI SDK 消费面）。

鉴权走 get_gateway_user（Bearer + X-API-Key 双通道）；路由保持轻薄，
业务编排与错误翻译在 OpenAiGatewayService。
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from novamind.features.agent_api.api.dependencies import get_gateway_user, get_gateway_service
from novamind.features.agent_api.schemas.gateway_schema import ChatCompletionRequest
from novamind.features.agent_api.services.openai_gateway_service import OpenAiGatewayService

router = APIRouter(tags=["OpenAI 兼容网关"])

_Service = Annotated[OpenAiGatewayService, Depends(get_gateway_service)]


@router.get("/models")
async def list_models(
    service: _Service,
    user: Annotated[dict, Depends(get_gateway_user)],
) -> dict:
    """列出当前 API key 归属用户已配置的 LLM 模型（OpenAI /v1/models 形状）。"""
    return await service.list_models(user["id"])
