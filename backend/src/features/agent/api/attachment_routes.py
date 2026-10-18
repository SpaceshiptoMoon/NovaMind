"""agent 聊天附件 API 路由：上传/下载/模型清单/健康检查。

原 features/qa ai_chat_routes（/api/v1/ai-chat/*），附件基础设施归位
agent 后收敛到 /api/v1/agent/attachments/*。models 与 health 端点随迁：
前者是附件上传前的模型探测入口，后者沿用原探活语义。
"""

import io
from typing import Annotated
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Path,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from novamind.core.auth import (
    get_current_user,
    get_current_user_optional,
)
from novamind.features.agent.attachments.schemas import (
    ChatAvailableModelsResponse,
    HealthCheckResponse,
    UploadChatAttachmentResponse,
)
from novamind.features.agent.attachments.service import AttachmentService
from novamind.features.agent.api.dependencies import (
    get_attachment_service,
    get_model_config_service,
)
from novamind.features.user.services.model_config_service import ModelConfigService

# LLM 生成参数默认值（models 端点回显用；与 user 侧模型配置默认一致）
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.8

router = APIRouter()


@router.post(
    "/attachments",
    response_model=UploadChatAttachmentResponse,
    summary="上传聊天附件",
    description="上传文档附件，返回附件ID用于后续聊天请求",
)
async def upload_chat_attachment(
    files: UploadFile = File(..., description="文档文件（支持 pdf/docx/txt/md，最大 20MB）"),
    attachment_service: AttachmentService = Depends(get_attachment_service),
    current_user: dict = Depends(get_current_user),
):
    """上传聊天附件。

    物理存储在 chat_attachments 表 + MinIO，前端（stores/agent.ts）与后端
    （chat_service._prepare）按 user_id 维度引用附件 id，不做会话级归属
    校验——同一用户可跨会话/跨 agent 复用附件，为既有设计决策。孤儿回收
    由 cron 任务 cleanup_orphan_attachments 负责（上传超 7 天且无引用）。
    """
    result = await attachment_service.upload_attachment(
        user_id=current_user["id"],
        file=files,
    )
    return UploadChatAttachmentResponse(**result)


@router.get(
    "/attachments/{attachment_id}/download",
    summary="下载聊天附件",
    description="根据附件ID下载文件",
)
async def download_chat_attachment(
    attachment_id: Annotated[int, Path(gt=0, description="附件ID")],
    attachment_service: AttachmentService = Depends(get_attachment_service),
    current_user: dict = Depends(get_current_user),
):
    """下载聊天附件"""
    attachment, file_content = await attachment_service.get_attachment_content(
        attachment_id, current_user["id"],
    )

    encoded_filename = quote(attachment.filename)
    return StreamingResponse(
        content=io.BytesIO(file_content),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="download"; '
                f"filename*=UTF-8''{encoded_filename}"
            )
        },
    )


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="健康检查",
    description="对话服务健康检查端点（可选认证：匿名可探活，携带有效 token 识别用户）",
)
async def health_check(
    current_user: dict | None = Depends(get_current_user_optional),
):
    """健康检查端点。探活用匿名放行；与其它业务端点统一走认证依赖链。"""
    return HealthCheckResponse(status="healthy", message="agent service is running")


@router.get(
    "/models",
    response_model=ChatAvailableModelsResponse,
    summary="获取可用模型",
    description="获取当前可用的AI模型列表及配置",
)
async def get_available_models(
    current_user: dict = Depends(get_current_user),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
):
    """获取可用模型列表（需要认证）"""
    user_id = current_user["id"]

    models: dict[str, dict] = {}

    # LLM 模型
    llm_models = await model_config_service.list_available_models(user_id, "llm")
    for model_name in llm_models:
        models[model_name] = {
            "max_tokens": DEFAULT_MAX_TOKENS,
            "temperature": DEFAULT_TEMPERATURE,
            "top_p": DEFAULT_TOP_P,
            "model_type": "llm",
        }

    # VLM 视觉模型
    vlm_models = await model_config_service.list_available_models(user_id, "vlm")
    for model_name in vlm_models:
        if model_name not in models:
            models[model_name] = {
                "max_tokens": 2048,
                "temperature": 0.7,
                "top_p": 0.8,
                "model_type": "vlm",
            }

    return ChatAvailableModelsResponse(models=models)
