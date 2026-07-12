"""
AI对话API路由
"""

from fastapi import APIRouter, Depends, Query, UploadFile, File, Path
from typing import Annotated, List
from fastapi.responses import StreamingResponse, Response
from urllib.parse import quote
import io

from novamind.features.user.api.auth import get_current_user
from novamind.features.qa.api.dependencies import get_aichat_service, get_qa_service, get_model_config_service, get_minio_client_for_presign
from novamind.features.qa.services.ai_chat_service import AIChatService
from novamind.features.qa.services.qa_service import QAService
from novamind.features.qa.api.constants import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, DEFAULT_TOP_P
from novamind.features.qa.schemas.ai_chat import (
    ChatRequest,
    ChatResponse,
    ChatHistoryResponse,
    HealthCheckResponse,
    AvailableModelsResponse,
    UploadChatAttachmentResponse,
)
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.storage.minio_client import enrich_attachments_with_presigned_urls

router = APIRouter()




@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="AI对话（非流式）",
    description="执行AI对话并返回完整响应",
)
async def chat(
    request: ChatRequest,
    ai_chat_service: AIChatService = Depends(get_aichat_service),
    current_user: dict = Depends(get_current_user),
):
    """执行AI对话（非流式）"""
    # 执行对话
    result = await ai_chat_service.chat(
        user_id=current_user["id"],
        session_id=request.session_id,
        content=request.content,
        llm_model=request.llm_model,
        enable_thinking=request.enable_thinking,
        attachment_ids=request.attachment_ids,
        enable_web_search=request.enable_web_search,
    )

    return ChatResponse(
        session_id=result["session_id"],
        user_message=result["user_message"],
        ai_message=result["ai_message"],
        conversation_history=result["conversation_history"]
    )


@router.post(
    "/chat-stream",
    response_class=StreamingResponse,
    summary="AI对话（流式）",
    description="执行AI流式对话，返回SSE格式的流式数据",
)
async def chat_stream(
    request: ChatRequest,
    ai_chat_service: AIChatService = Depends(get_aichat_service),
    current_user: dict = Depends(get_current_user),
):
    """
    执行AI流式对话

    返回Server-Sent Events (SSE)格式的流式数据。

    事件类型：
    - user_message: 用户消息信息
    - sources: 检索来源引用列表（启用 RAG/联网时，在正文流式前下发）
    - reasoning: 思考过程片段（开启深度思考时）
    - content: AI生成的文本片段
    - done: 对话完成，包含完整的AI回复与来源/回答状态
    - error: 错误信息

    使用示例（前端）：
    ```javascript
    const response = await fetch('/ai-chat/chat-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: '你好', session_id: 'xxx' })
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const text = decoder.decode(value);
        const lines = text.split('\\n\\n');

        for (const line of lines) {
            if (line.startsWith('data: ')) {
                const data = JSON.parse(line.slice(6));
                console.log(data);
            }
        }
    }
    ```
    """
    async def generate():
        async for chunk in ai_chat_service.chat_stream(
            user_id=current_user["id"],
            session_id=request.session_id,
            content=request.content,
            llm_model=request.llm_model,
            enable_thinking=request.enable_thinking,
            attachment_ids=request.attachment_ids,
            enable_web_search=request.enable_web_search,
        ):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.get(
    "/chat-history",
    response_model=ChatHistoryResponse,
    summary="获取聊天历史",
    description="获取指定会话的聊天历史记录",
)
async def get_chat_history(
    session_id: Annotated[str, Query(min_length=1, description="会话ID")],
    qa_service: QAService = Depends(get_qa_service),
    current_user: dict = Depends(get_current_user),
    minio_client=Depends(get_minio_client_for_presign),
):
    """获取聊天历史"""
    messages = await qa_service.get_session_messages(
        session_id, current_user["id"]
    )

    if minio_client:
        for msg in messages:
            await enrich_attachments_with_presigned_urls(msg.extra, minio_client)

    return ChatHistoryResponse(
        session_id=session_id,
        messages=[
            {
                "id": msg.id,
                "content": msg.content,
                "role": msg.role,
                "extra": msg.extra,
                "created_at": msg.created_at,
            }
            for msg in messages
        ]
    )


@router.delete(
    "/clear-chat",
    status_code=204,
    summary="清除聊天历史",
    description="清除指定会话的所有聊天记录",
)
async def clear_chat_history(
    session_id: Annotated[str, Query(min_length=1, description="会话ID")],
    qa_service: QAService = Depends(get_qa_service),
    current_user: dict = Depends(get_current_user),
):
    """清除聊天历史"""
    await qa_service.delete_session(
        session_id, current_user["id"]
    )

    return Response(status_code=204)


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
    """上传聊天附件"""
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
    attachment = await ai_chat_service.attachment_repo.get_by_id(attachment_id)
    if not attachment or attachment.user_id != current_user["id"]:
        from novamind.features.qa.api.exceptions import ChatAttachmentNotFoundError
        raise ChatAttachmentNotFoundError(attachment_id)

    file_content = await ai_chat_service.minio_client.download_document(
        ai_chat_service.minio_client.default_bucket,
        attachment.storage_path,
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
    description="AI对话服务健康检查端点",
)
async def health_check():
    """健康检查端点"""
    return HealthCheckResponse(status="healthy", message="AI chat service is running")


@router.get(
    "/models",
    response_model=AvailableModelsResponse,
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

    return AvailableModelsResponse(models=models)
