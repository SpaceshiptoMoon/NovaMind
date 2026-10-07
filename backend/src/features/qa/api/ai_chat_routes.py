"""
AI 对话 API 路由（共享基础设施）

批4 工作台统一后，对话唯一入口是 agent 对话面；QA 对话端点（POST /chat
与 /ws）已清退，本路由仅保留 agent 侧复用的共享端点：附件上传/下载、
模型清单、健康检查。
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
from novamind.features.qa.api.constants import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
)
from novamind.features.qa.api.dependencies import (
    get_aichat_service,
    get_model_config_service,
)
from novamind.features.qa.schemas.ai_chat import (
    ChatAvailableModelsResponse,
    HealthCheckResponse,
    UploadChatAttachmentResponse,
)
from novamind.features.qa.services.ai_chat_service import AIChatService
from novamind.features.user.services.model_config_service import ModelConfigService

router = APIRouter()


@router.post(
    "/chat-attachments",
    response_model=UploadChatAttachmentResponse,
    summary="上传聊天附件",
    description="上传文档附件，返回附件ID用于后续聊天请求",
)
async def upload_chat_attachment(
    files: UploadFile = File(..., description="文档文件（支持 pdf/docx/txt/md，最大 20MB）"),
    ai_chat_service: AIChatService = Depends(get_aichat_service),
    current_user: dict = Depends(get_current_user),
):
    """上传聊天附件。

    共享端点：agent 对话（/agent/agents/{id}/ws）与 QA 归档数据共用。
    物理归属在 features/qa（chat_attachments 表 + MinIO），agent 前端
    （stores/agent.ts）与后端（features/agent/chat_service._prepare）均按
    user_id 维度引用附件 id，不做会话级归属校验——同一用户可跨会话/跨
    agent 复用附件，为既有设计决策，勿在单个 feature 内改动此语义。
    孤儿回收由 cron 任务 cleanup_orphan_attachments 负责（上传超 7 天且无引用）。
    """
    result = await ai_chat_service.upload_attachment(
        user_id=current_user["id"],
        file=files,
    )
    return UploadChatAttachmentResponse(**result)


@router.get(
    "/chat-attachments/{attachment_id}/download",
    summary="下载聊天附件",
    description="根据附件ID下载文件",
)
async def download_chat_attachment(
    attachment_id: Annotated[int, Path(gt=0, description="附件ID")],
    ai_chat_service: AIChatService = Depends(get_aichat_service),
    current_user: dict = Depends(get_current_user),
):
    """下载聊天附件"""
    attachment, file_content = await ai_chat_service.get_attachment_content(
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
    description="AI对话服务健康检查端点（可选认证：匿名可探活，携带有效 token 识别用户）",
)
async def health_check(
    current_user: dict | None = Depends(get_current_user_optional),
):
    """健康检查端点。探活用匿名放行；与其它业务端点统一走认证依赖链。"""
    return HealthCheckResponse(status="healthy", message="AI chat service is running")


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
