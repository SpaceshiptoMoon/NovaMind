"""OpenAI 兼容网关路由：/v1/models 与 /v1/chat/completions（外部 OpenAI SDK 消费面）。

鉴权走 get_gateway_user（Bearer + X-API-Key 双通道）；路由只做异常→OpenAI
错误响应的转译边界，业务编排与能力协商在 OpenAiGatewayService。
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from novamind.shared.ai_models.errors import ModelProviderError

from novamind.features.agent_api.api.dependencies import (
    get_gateway_service,
    get_gateway_user,
)
from novamind.features.agent_api.exceptions import AgentApiError
from novamind.features.agent_api.schemas.gateway_schema import ChatCompletionRequest
from novamind.features.agent_api.services.openai_gateway_service import (
    GatewayRequestError,
    OpenAiGatewayService,
    provider_error_to_openai,
)

router = APIRouter(tags=["OpenAI 兼容网关"])

_Service = Annotated[OpenAiGatewayService, Depends(get_gateway_service)]


def _error_response(exc: Exception) -> JSONResponse:
    """网关域异常 → OpenAI 错误 JSONResponse（非网关域异常原样上抛走全局兜底）。"""
    if isinstance(exc, GatewayRequestError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_body())
    if isinstance(exc, AgentApiError):
        status = exc.__class__.__dict__.get("http_status_code") or 400
        return JSONResponse(
            status_code=status,
            content={
                "error": {"message": exc.message, "type": "invalid_request_error",
                          "param": None, "code": exc.code},
            },
        )
    if isinstance(exc, ModelProviderError):
        status, body = provider_error_to_openai(exc)
        return JSONResponse(status_code=status, content=body)
    raise exc


@router.get("/models")
async def list_models(
    service: _Service,
    user: Annotated[dict, Depends(get_gateway_user)],
) -> dict:
    """列出当前 API key 归属用户已配置的 LLM 模型（OpenAI /v1/models 形状）。"""
    return await service.list_models(user["id"])


@router.post("/chat/completions")
async def create_chat_completion(
    req: ChatCompletionRequest,
    service: _Service,
    user: Annotated[dict, Depends(get_gateway_user)],
):
    """OpenAI 兼容对话补全：非流式返回完整 JSON，stream=true 走 SSE。

    异常在路由边界统一转译为 OpenAI 错误信封（外部 SDK 只认该格式）。
    """
    try:
        if req.stream:
            from fastapi.responses import StreamingResponse

            ctx = await service.prepare_stream(user["id"], req)
            return StreamingResponse(
                service.stream_chat_completion(ctx),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return await service.create_chat_completion(user["id"], req)
    except (GatewayRequestError, ModelProviderError, AgentApiError) as e:
        return _error_response(e)
