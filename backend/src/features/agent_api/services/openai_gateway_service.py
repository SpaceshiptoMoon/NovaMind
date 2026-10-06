"""OpenAI 兼容网关服务：模型清单 + chat/completions 编排。

网关把用户已配置的 LLM（ModelConfigService 公共面）以 OpenAI 协议对外暴露。
职责边界：
- 错误翻译收敛于此：ModelProviderError → OpenAI 错误信封（HTTP 语义归 feature 层）；
- 能力协商与工作台同语义（resolve_capabilities），失败方向安全；
- 直连已配模型名，不做别名映射。
"""
from __future__ import annotations

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.ai_models.errors import (
    ModelProviderError,
    ModelQuotaError,
    ModelRateLimitError,
)
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# OpenAI 错误 type 惯例值（SDK 据此决定重试策略与错误归类）
_TYPE_INVALID_REQUEST = "invalid_request_error"
_TYPE_RATE_LIMIT = "rate_limit_error"
_TYPE_API_ERROR = "api_error"


def provider_error_to_openai(exc: ModelProviderError) -> tuple[int, dict]:
    """ModelProviderError → (HTTP 状态码, OpenAI 错误信封)。

    映射依据官方语义：429→rate_limit_error（SDK 自动退避重试）、
    额度类→insufficient_quota（OpenAI 同款 code）、5xx→api_error、
    其余 4xx→invalid_request_error。
    """
    status = exc.status_code
    if isinstance(exc, ModelRateLimitError):
        err_type, code = _TYPE_RATE_LIMIT, "rate_limit_exceeded"
        status = 429
    elif isinstance(exc, ModelQuotaError):
        err_type, code = _TYPE_INVALID_REQUEST, "insufficient_quota"
        if status is None:
            status = 400
    elif status is not None and status >= 500:
        err_type, code = _TYPE_API_ERROR, "provider_error"
    else:
        err_type, code = _TYPE_INVALID_REQUEST, "provider_error"
        if status is None:
            status = 502
    return status, {
        "error": {
            "message": exc.message,
            "type": err_type,
            "param": None,
            "code": code,
        }
    }


class OpenAiGatewayService:
    """OpenAI 兼容网关编排服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_models(self, user_id: int) -> dict:
        """列出当前用户已配置的 LLM 模型（OpenAI /v1/models 响应形状）。

        同名模型多协议配置时按模型名去重（created_at 取最早）。

        Returns:
            {"object": "list", "data": [{"id", "object", "created", "owned_by"}]}
        """
        from novamind.features.user.services.model_config_service import ModelConfigService

        configs = await ModelConfigService(self.session).list_configs(user_id, "llm")
        seen: dict[str, int] = {}
        for item in configs.items:
            created = int(item.created_at.timestamp()) if item.created_at else 0
            if item.model not in seen or created < seen[item.model]:
                seen[item.model] = created
        data = [
            {"id": model, "object": "model", "created": created, "owned_by": "novamind"}
            for model, created in sorted(seen.items())
        ]
        return {"object": "list", "data": data}
