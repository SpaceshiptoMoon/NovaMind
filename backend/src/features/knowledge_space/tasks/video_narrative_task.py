"""视频叙事文档任务：arq 异步合成（解析完成自动入队 / API 按需触发共用）。"""
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


async def process_narrative_task(
    ctx,
    space_id: int,
    kb_id: int,
    document_id: int,
    llm_model: str | None = None,
    user_id: int = 1,
) -> dict:
    """异步合成视频叙事文档（拉块 → 引擎 Map-Reduce → 落库）。

    Args:
        ctx: arq 上下文（含 job_id）。
        space_id / kb_id / document_id: 目标视频文档归属。
        llm_model: 合成用 LLM 模型名（None 用触发者默认 LLM）。
        user_id: 触发者用户 ID（模型归属解析基准；解析完成钩子未传时取文档上传者）。

    Returns:
        {"status": "completed"|"failed", "chunks_used": int, "error": str|None}
    """
    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.services.video_narrative_service import (
        VideoNarrativeService,
    )
    from novamind.features.user.services.model_config_service import ModelConfigService

    async with get_db_session() as session:
        mcs = ModelConfigService(session)
        # 模型归属文档上传者：无显式 llm_model 时取其默认 LLM（"没选不兜底"仅约束
        # kb 显式配置；任务侧的默认档是产品决策的生产默认，非静默串用）
        try:
            from novamind.features.knowledge_space.repository.document_repository import (
                DocumentRepository,
            )
            doc = await DocumentRepository(session).get_by_id(document_id)
            owner_id = user_id if user_id else (doc.uploader_id if doc else 1)
        except Exception:
            owner_id = user_id or 1
        if not llm_model:
            llm_model = await mcs.get_user_default_model_name(owner_id, "llm")
        llm_client = await mcs.get_llm_client_by_model(owner_id, llm_model)

        service = VideoNarrativeService(session, llm_client=llm_client, llm_model=llm_model or "")
        return await service.synthesize(
            space_id=space_id, kb_id=kb_id, document_id=document_id,
        )


async def enqueue_narrative_synthesis(
    space_id: int,
    kb_id: int,
    document_id: int,
    llm_model: str | None = None,
    user_id: int = 1,
) -> str | None:
    """入队叙事合成任务（fire-and-forget：解析完成路径不因入队失败阻断）。"""
    from novamind.shared.mq import get_arq_pool

    try:
        pool = await get_arq_pool()
        job = await pool.enqueue_job(
            "process_narrative_task",
            space_id=space_id, kb_id=kb_id, document_id=document_id,
            llm_model=llm_model, user_id=user_id,
        )
        logger.info(
            "视频叙事合成已入队", kb_id=kb_id, document_id=document_id,
            job_id=job.job_id if job else None,
        )
        return job.job_id if job else None
    except Exception as e:
        logger.warning(
            "视频叙事合成入队失败（不影响解析主流程）",
            kb_id=kb_id, document_id=document_id, error=str(e),
        )
        return None
