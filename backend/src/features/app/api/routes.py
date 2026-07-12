"""
简历挖掘 API 路由
"""
import json
import os
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.api.dependencies import get_current_user_id
from novamind.core.database.database import get_db
from novamind.features.app.api.dependencies import _get_model_config_service
from novamind.features.app.api.exceptions import ResumeSessionNotFoundError, ResumeParseError, InvalidFileTypeError, InvalidConfigError, FileSizeExceededError
from novamind.features.app.models.resume import ResumeSessionStatus
from novamind.features.app.repository.resume_repository import ResumeSessionRepository
from novamind.features.app.schemas.resume_schema import (
    ResumeSessionResponse, ResumeSessionListResponse, StructuredResume,
)
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.clients import get_minio_client
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# 文件上传限制
ALLOWED_RESUME_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}
MAX_RESUME_SIZE = 50 * 1024 * 1024  # 50MB


# ==================== 简历挖掘 ====================

@router.post("/resume/upload", response_model=ResumeSessionResponse)
async def upload_resume(
    file: UploadFile = File(...),
    jd_text: str = Form(""),
    config: str = Form("{}"),
    llm_model: str = Form(""),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    model_config_service: ModelConfigService = Depends(_get_model_config_service),
):
    # 解析 LLM 模型：前端传入 > 用户默认
    model = llm_model or await model_config_service.get_user_default_model_name(user_id, "llm")
    if not model:
        raise ResumeParseError("未配置 LLM 模型")

    # 文件类型校验
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_RESUME_EXTENSIONS:
        raise InvalidFileTypeError(ext, ", ".join(sorted(ALLOWED_RESUME_EXTENSIONS)))

    # 解析并校验 config 参数
    try:
        cfg = json.loads(config) if config else {}
    except json.JSONDecodeError:
        raise InvalidConfigError("config 参数不是合法的 JSON")
    if not isinstance(cfg, dict):
        raise InvalidConfigError("config 参数必须是 JSON 对象")
    # 基本字段类型校验
    if "breadth" in cfg and not isinstance(cfg["breadth"], int):
        raise InvalidConfigError("config.breadth 必须是整数")
    if "depth" in cfg and not isinstance(cfg["depth"], int):
        raise InvalidConfigError("config.depth 必须是整数")
    if "llm_model" in cfg and not isinstance(cfg["llm_model"], str):
        raise InvalidConfigError("config.llm_model 必须是字符串")
    if llm_model:
        cfg["llm_model"] = llm_model

    # 读取文件内容（在请求上下文内完成）
    file_bytes = await file.read()
    if len(file_bytes) > MAX_RESUME_SIZE:
        raise FileSizeExceededError(MAX_RESUME_SIZE // 1024 // 1024)
    filename = file.filename or "unknown"

    session_repo = ResumeSessionRepository(db)
    session = await session_repo.create({
        "user_id": user_id,
        "resume_filename": filename,
        "jd_text": jd_text or None,
        "status": ResumeSessionStatus.PARSING,
        "config": cfg,
    })
    await db.commit()

    # 存原始文件到 MinIO
    session_id = session.id
    try:
        minio_client = await get_minio_client()
        original_path = f"resume/{session_id}/{filename}"
        await minio_client.upload_file(original_path, file_bytes)
        await session_repo.update(session_id, {"resume_file_url": original_path})
        await db.commit()
    except Exception as e:
        logger.warning("原始文件上传 MinIO 失败", session_id=session_id, error=str(e))
        cfg["file_upload_warning"] = "原始文件存储失败，但不影响解析"

    # 后台异步执行 S1-S12 全流程（通过 arq 队列，支持重试和恢复）
    from novamind.shared.mq import enqueue_process_resume

    await enqueue_process_resume(
        session_id=str(session_id),
        user_id=user_id,
        llm_model=model,
        jd_text=jd_text or None,
        config=cfg,
        file_bytes=file_bytes,
        filename=filename,
    )

    # 立即返回会话（status=parsing）
    session = await session_repo.get_by_id(session_id)
    return _to_session_response(session)


@router.get("/resume/sessions", response_model=ResumeSessionListResponse)
async def list_resume_sessions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[int] = Query(None, description="按状态筛选"),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    repo = ResumeSessionRepository(db)
    sessions, total = await repo.list_by_user(user_id, limit, offset, status=status)
    return ResumeSessionListResponse(
        sessions=[_to_session_response(s) for s in sessions],
        total=total,
    )


@router.get("/resume/sessions/{session_id}", response_model=ResumeSessionResponse)
async def get_resume_session(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    repo = ResumeSessionRepository(db)
    session = await repo.get_by_id(session_id)
    if not session or session.user_id != user_id:
        raise ResumeSessionNotFoundError(session_id)
    return _to_session_response(session)


@router.get("/resume/sessions/{session_id}/report")
async def get_report_content(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取报告 MD 文本内容（从 MinIO 读取）"""
    repo = ResumeSessionRepository(db)
    session = await repo.get_by_id(session_id)
    if not session or session.user_id != user_id:
        raise ResumeSessionNotFoundError(session_id)

    if not session.md_report_url:
        raise ResumeParseError("报告尚未生成")

    try:
        minio_client = await get_minio_client()
        content = await minio_client.download_document(minio_client.default_bucket, session.md_report_url)
        return Response(content=content, media_type="text/markdown")
    except Exception as e:
        logger.error("从 MinIO 读取报告失败", session_id=session_id, error=str(e))
        raise ResumeParseError("报告读取失败")


@router.get("/resume/sessions/{session_id}/download")
async def download_report(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """下载报告 MD 文件（从 MinIO 读取）"""
    repo = ResumeSessionRepository(db)
    session = await repo.get_by_id(session_id)
    if not session or session.user_id != user_id:
        raise ResumeSessionNotFoundError(session_id)

    if not session.md_report_url:
        raise ResumeParseError("报告尚未生成")

    try:
        minio_client = await get_minio_client()
        content = await minio_client.download_document(minio_client.default_bucket, session.md_report_url)
    except Exception as e:
        logger.error("从 MinIO 读取报告失败", session_id=session_id, error=str(e))
        raise ResumeParseError("报告读取失败")

    filename = (session.resume_filename or "resume").rsplit(".", 1)[0] + "_report.md"
    encoded_filename = quote(filename)
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


@router.delete("/resume/sessions/{session_id}")
async def delete_resume_session(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """删除简历会话及其 MinIO 文件"""
    repo = ResumeSessionRepository(db)
    session = await repo.get_by_id(session_id)
    if not session or session.user_id != user_id:
        raise ResumeSessionNotFoundError(session_id)

    # 删除 MinIO 文件
    try:
        minio_client = await get_minio_client()
        if session.resume_file_url:
            await minio_client.delete_document(minio_client.default_bucket, session.resume_file_url)
        if session.md_report_url:
            await minio_client.delete_document(minio_client.default_bucket, session.md_report_url)
    except Exception as e:
        logger.warning("删除 MinIO 文件失败", session_id=session_id, error=str(e))

    await repo.delete_by_id(session_id)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/resume/sessions/{session_id}/cancel")
async def cancel_resume_session(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """取消正在处理的简历会话"""
    from novamind.shared.mq.task_tracker import mark_resume_cancelled

    repo = ResumeSessionRepository(db)
    session = await repo.get_by_id(session_id)
    if not session or session.user_id != user_id:
        raise ResumeSessionNotFoundError(session_id)

    # 只有正在处理中的会话才能取消
    if session.status not in (
        ResumeSessionStatus.PARSING,
        ResumeSessionStatus.ANALYZING,
        ResumeSessionStatus.PROBING,
    ):
        raise ResumeParseError("当前会话状态不允许取消")

    await mark_resume_cancelled(session_id)
    return {"message": "取消请求已发送"}


# ==================== Helper ====================

def _to_session_response(session) -> ResumeSessionResponse:
    sr = session.structured_resume
    return ResumeSessionResponse(
        id=session.id,
        user_id=session.user_id,
        resume_filename=session.resume_filename or "",
        structured_resume=StructuredResume(**sr) if sr else None,
        jd_text=session.jd_text or "",
        md_report_url=session.md_report_url or None,
        status=session.status,
        config=session.config or {},
        error_message=session.error_message or None,
        created_at=session.created_at.isoformat() if session.created_at else None,
        updated_at=session.updated_at.isoformat() if session.updated_at else None,
    )
