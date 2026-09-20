"""文档域任务追踪（批次 6.4 从 shared/mq/task_tracker 下沉）。

文档域函数归 knowledge_space；通用 TaskTracker 类留 shared/mq。
doc_tracker 单例随迁（键名不变，Redis 数据兼容）。
"""
from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.mq.task_tracker import doc_tracker

logger = get_logger(__name__)

async def bind_job_to_document(document_id: int, job_id: str) -> None:
    await doc_tracker.bind(document_id, job_id)



async def get_job_id_for_document(document_id: int) -> str | None:
    return await doc_tracker.get_job_id(document_id)



async def unbind_job(document_id: int) -> None:
    await doc_tracker.unbind(document_id)



async def get_active_document_count() -> int:
    return await doc_tracker.get_active_count()



async def is_document_actively_processing(document_id: int) -> bool:
    """检查文档是否真的还在处理中（验证 job 是否存活）"""
    job_id = await doc_tracker.get_job_id(document_id)
    if not job_id:
        return False
    try:
        from arq.jobs import Job
        from novamind.shared.mq import get_arq_pool
        pool = await get_arq_pool()
        # arq 0.28 的 _get_job_result 需要内部 bytes key，不适合直接传 str job_id。
        # 这里改用公开 Job API，但只把“仍在队列中的 job”视为活跃。
        job = Job(job_id, pool, _deserializer=pool.job_deserializer)

        job_result = await job.result_info()
        if job_result is not None:
            await doc_tracker.unbind(document_id)
            logger.info("任务已结束，清理任务映射", document_id=document_id, job_id=job_id)
            return False

        queued_job = await job.info()
        if queued_job is not None:
            return True

        await doc_tracker.unbind(document_id)
        logger.info("清理残留任务映射", document_id=document_id, job_id=job_id)
        return False
    except Exception as e:
        # 无法验证时允许重试，避免文档永远卡死在 PROCESSING
        logger.warning("无法验证任务状态，允许重试", document_id=document_id, job_id=job_id, error=str(e))
        return False



async def purge_document_jobs(document_id: int, *, exclude_job_id: str | None = None) -> list:
    """清理 arq 层指向该文档的所有残留僵尸 job（不依赖 worker 存活）。

    背景（doc 574 事故）：worker 崩溃或孤儿恢复只推进了 DB 任务状态，
    arq 队列条目 / job 定义 / in-progress 键与 tracker 映射无人清理，
    job 永久残留导致文档被误判「正在处理」而无法重试，且一旦被 worker
    消费还会复活已终结的任务重跑。

    arq 的 ``Job.abort()`` 依赖存活 worker 消费 abort 队列，worker 已死时
    永远等不到结果，故此处直接做 Redis 键手术；同时写入 abort-jobs 信号，
    若 worker 仍存活且该 job 恰在执行，可触发协作式取消。

    Args:
        document_id: 文档 ID
        exclude_job_id: 跳过该 job（孤儿恢复重入队场景下保护新 job）

    Returns:
        被清理的 job_id 列表
    """
    import pickle
    import time

    import arq.constants as arq_constants
    from novamind.shared.mq import get_arq_pool

    pool = await get_arq_pool()
    queue_name = getattr(pool, "queue_name", "arq:queue")

    # 候选集 = tracker 当前绑定的 job（可能已不在队列、仅键残留）
    #         ∪ 队列中指向该文档的 process_document_task job
    #           （含 job_id 已不被任何 DB 字段引用的旧 job，如 doc-task-{task_id} 格式）
    tracked_job_id = await doc_tracker.get_job_id(document_id)
    candidates = {tracked_job_id} if tracked_job_id else set()
    for raw_id in await pool.zrange(queue_name, 0, -1):
        candidates.add(raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id))
    candidates.discard(exclude_job_id)

    purged: list = []
    now_ms = int(time.time() * 1000)
    for job_id in sorted(candidates):
        job_def_raw = await pool.get(arq_constants.job_key_prefix + job_id)
        if not job_def_raw:
            continue
        try:
            job_def = pickle.loads(job_def_raw)
        except Exception as e:
            logger.warning(
                "残留 job 定义反序列化失败，跳过",
                document_id=document_id,
                job_id=job_id,
                error=str(e),
            )
            continue
        if job_def.get("f") != "process_document_task":
            continue
        if (job_def.get("k") or {}).get("document_id") != document_id:
            continue

        # abort 信号：worker 存活且该 job 正在执行时可触发取消
        await pool.zadd(arq_constants.abort_jobs_ss, {job_id: now_ms})
        # 键手术：worker 已死时 abort 队列无人消费，直接移除 arq 层键
        await pool.zrem(queue_name, job_id)
        await pool.delete(
            arq_constants.job_key_prefix + job_id,
            arq_constants.retry_key_prefix + job_id,
            arq_constants.in_progress_key_prefix + job_id,
        )
        purged.append(job_id)

    if purged:
        logger.warning(
            "已清理文档残留 arq 僵尸 job",
            document_id=document_id,
            purged_job_ids=purged,
        )
    return purged



async def mark_document_cancelled(document_id: int) -> None:
    await doc_tracker.mark_cancelled(document_id)



async def is_document_cancelled(document_id: int) -> bool:
    return await doc_tracker.is_cancelled(document_id)



async def clear_cancel_flag(document_id: int) -> None:
    await doc_tracker.clear_cancel(document_id)

