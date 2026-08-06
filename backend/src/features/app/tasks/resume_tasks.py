"""
简历挖掘 arq 任务函数与宿主编排。
"""
from typing import Optional

from novamind.shared.logging import get_logger

logger = get_logger(__name__)


async def process_resume_task(
    ctx: dict,
    session_id: str,
    user_id: int,
    llm_model: str,
    jd_text: Optional[str],
    config: dict,
    file_bytes: bytes,
    filename: str,
) -> None:
    """
    arq 任务函数：执行完整的简历挖掘 S1-S12 pipeline

    流程：
    1. 幂等性校验（仅处理合法状态）
    2. 调用 ResumePipelineService.execute_pipeline
    3. 成功时移除追踪映射
    4. 失败时 arq 自动重试，最终失败执行三层兜底
    """
    from novamind.shared.mq.task_tracker import unbind_resume_job, is_resume_cancelled, clear_resume_cancel_flag

    job_id = ctx.get("job_id", "unknown")

    logger.info(
        "arq 任务开始：简历挖掘",
        session_id=session_id,
        job_id=job_id,
    )

    # 前置取消检查
    if await is_resume_cancelled(session_id):
        await _ensure_mark_resume_failed(session_id, "[用户取消] 简历挖掘已被用户取消")
        await clear_resume_cancel_flag(session_id)
        await unbind_resume_job(session_id)
        return

    try:
        from novamind.features.app.services.resume_pipeline_service import ResumePipelineService
        await ResumePipelineService.execute_pipeline(
            session_id=session_id,
            user_id=user_id,
            llm_model=llm_model,
            jd_text=jd_text,
            config=config,
            file_bytes=file_bytes,
            filename=filename,
        )

        await unbind_resume_job(session_id)
        logger.info("arq 任务完成：简历挖掘成功", session_id=session_id, job_id=job_id)

    except Exception as e:
        logger.error(
            "arq 任务失败：简历挖掘异常",
            session_id=session_id,
            job_id=job_id,
            error=str(e),
        )

        job_try = ctx.get("job_try", 1)
        max_tries = ctx.get("max_tries", 3)
        if job_try >= max_tries:
            await _ensure_mark_resume_failed(session_id, str(e))
            await unbind_resume_job(session_id)
        else:
            raise


async def _ensure_mark_resume_failed(session_id: str, error_message: str) -> None:
    """
    强制将简历会话标记为 FAILED，三层兜底

    1. ORM 独立 session
    2. Raw SQL
    3. 记录严重告警等待 recover_orphan_resume_sessions 处理
    """
    failed_msg = f"[已重试最大次数] {error_message}"

    # 第 1 层：ORM 独立 session
    try:
        from novamind.core.database.database import get_db_session
        from novamind.features.app.repository.resume_repository import ResumeSessionRepository
        from novamind.features.app.models.resume import ResumeSessionStatus

        async with get_db_session() as independent_session:
            repo = ResumeSessionRepository(independent_session)
            session = await repo.get_by_id(session_id)
            if session:
                await repo.update(session_id, {
                    "status": ResumeSessionStatus.FAILED,
                    "error_message": failed_msg[:2000],
                })
                await independent_session.commit()
                logger.info("简历会话已标记 FAILED（ORM）", session_id=session_id)
                return
    except Exception as e:
        logger.warning("ORM 标记简历 FAILED 失败，尝试 raw SQL", session_id=session_id, error=str(e))

    # 第 2 层：Raw SQL（下沉 ResumeSessionRepository.mark_failed_independent）
    try:
        from novamind.features.app.models.resume import ResumeSessionStatus
        from novamind.features.app.repository.resume_repository import ResumeSessionRepository

        await ResumeSessionRepository.mark_failed_independent(
            session_id, ResumeSessionStatus.FAILED.value, failed_msg
        )
        logger.info("简历会话已标记 FAILED（raw SQL）", session_id=session_id)
        return
    except Exception as e:
        logger.error("raw SQL 标记简历 FAILED 也失败", session_id=session_id, error=str(e))

    # 第 3 层：记录严重告警
    logger.critical(
        "简历会话状态更新全部失败，会话将卡在中间状态直到服务重启",
        session_id=session_id,
    )


async def recover_orphan_resume_sessions() -> int:
    """
    恢复孤儿简历会话：查询所有 PARSING/ANALYZING/PROBING 状态的会话，重新入队

    场景：服务意外重启后，之前正在处理的简历会话需要恢复。
    对已重试次数过多的会话直接标记为 FAILED，避免无限循环。

    Returns:
        恢复的会话数量
    """
    from novamind.core.database.database import get_db_session
    from novamind.setting.yaml_config import get_config
    from novamind.features.app.models.resume import ResumeSession, ResumeSessionStatus
    from sqlalchemy import select, or_

    recovered = 0
    max_tries = get_config().task_queue.max_tries

    async with get_db_session() as session:
        result = await session.execute(
            select(ResumeSession).where(
                or_(
                    ResumeSession.status == ResumeSessionStatus.PARSING,
                    ResumeSession.status == ResumeSessionStatus.ANALYZING,
                    ResumeSession.status == ResumeSessionStatus.PROBING,
                )
            )
        )
        sessions = result.scalars().all()

        if not sessions:
            logger.info("无需恢复的孤儿简历会话")
            return 0

        for s in sessions:
            cfg = s.config or {}
            retry_count = cfg.get("recover_retry_count", 0)

            if retry_count >= max_tries:
                # 超过恢复次数限制，直接标记失败
                s.status = ResumeSessionStatus.FAILED
                s.error_message = "[恢复重试次数超限，需人工介入]"
                s.config = {**cfg, "recover_retry_count": retry_count + 1}
                await session.commit()
                logger.warning(
                    "孤儿简历会话恢复次数超限，已标记失败",
                    session_id=s.id,
                    retry_count=retry_count,
                    max_tries=max_tries,
                )
                continue

            try:
                # 更新恢复重试计数
                s.config = {**cfg, "recover_retry_count": retry_count + 1}
                await session.commit()

                # 读取 MinIO 文件
                from novamind.shared.clients import ClientFactory
                minio_client = await ClientFactory.get_minio_client()
                file_bytes = await minio_client.download_document(
                    minio_client.default_bucket, s.resume_file_url
                )

                await enqueue_process_resume(
                    session_id=str(s.id),
                    user_id=s.user_id,
                    llm_model=s.config.get("llm_model", ""),
                    jd_text=s.jd_text,
                    config=s.config or {},
                    file_bytes=file_bytes,
                    filename=s.resume_filename or "unknown",
                )
                recovered += 1
                logger.info(
                    "孤儿简历会话已重新入队",
                    session_id=s.id,
                    retry_count=retry_count + 1,
                    max_tries=max_tries,
                )
            except Exception as e:
                logger.error(
                    "孤儿简历会话恢复失败",
                    session_id=s.id,
                    error=str(e),
                )

    logger.info("孤儿简历会话恢复完成", recovered=recovered)
    return recovered


async def enqueue_process_resume(
    session_id: str,
    user_id: int,
    llm_model: str,
    jd_text: Optional[str],
    config: dict,
    file_bytes: bytes,
    filename: str,
) -> str:
    """
    将简历挖掘任务入队

    Args:
        session_id: 简历会话 ID
        user_id: 用户 ID
        llm_model: LLM 模型名称
        jd_text: 岗位描述（可选）
        config: 配置参数
        file_bytes: 简历文件内容
        filename: 文件名

    Returns:
        job_id: arq 任务 ID
    """
    from novamind.shared.mq import get_arq_pool
    from novamind.shared.mq.task_tracker import bind_job_to_resume

    pool = await get_arq_pool()

    job = await pool.enqueue_job(
        "process_resume_task",
        session_id=session_id,
        user_id=user_id,
        llm_model=llm_model,
        jd_text=jd_text,
        config=config,
        file_bytes=file_bytes,
        filename=filename,
    )

    job_id = job.job_id
    await bind_job_to_resume(session_id, job_id)

    logger.info(
        "简历挖掘任务已入队",
        session_id=session_id,
        job_id=job_id,
    )
    return job_id