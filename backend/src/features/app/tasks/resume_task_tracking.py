"""resume 域任务追踪（批次 6.4 从 shared/mq/task_tracker 下沉）。

resume 域函数归 app feature；通用 TaskTracker 类留 shared/mq。
resume_tracker 单例随迁（键名不变，Redis 数据兼容）。
"""
from novamind.shared.mq.task_tracker import resume_tracker


async def bind_job_to_resume(session_id: str, job_id: str) -> None:
    """绑定简历会话与 arq 任务 ID（供取消/状态查询定位任务）。

    Args:
        session_id: 简历会话主键（字符串形式）。
        job_id: arq 任务 ID。

    Returns:
        无。
    """
    await resume_tracker.bind(session_id, job_id)



async def get_job_id_for_resume(session_id: str) -> str | None:
    """查简历会话绑定的 arq 任务 ID，无绑定返回 None。

    Args:
        session_id: 简历会话主键（字符串形式）。

    Returns:
        绑定的 arq 任务 ID；未绑定返回 None。
    """
    return await resume_tracker.get_job_id(session_id)



async def unbind_resume_job(session_id: str) -> None:
    """解除简历会话的任务绑定（任务完结后调用）。

    Args:
        session_id: 简历会话主键（字符串形式）。

    Returns:
        无。
    """
    await resume_tracker.unbind(session_id)



async def mark_resume_cancelled(session_id: str) -> None:
    """置简历会话取消标记，运行中的任务据此提前退出。

    Args:
        session_id: 简历会话主键（字符串形式）。

    Returns:
        无。
    """
    await resume_tracker.mark_cancelled(session_id)



async def is_resume_cancelled(session_id: str) -> bool:
    """查询简历会话是否已被请求取消。

    Args:
        session_id: 简历会话主键（字符串形式）。

    Returns:
        已请求取消为 True。
    """
    return await resume_tracker.is_cancelled(session_id)



async def clear_resume_cancel_flag(session_id: str) -> None:
    """清除简历会话的取消标记（会话重置/复用时调用）。

    Args:
        session_id: 简历会话主键（字符串形式）。

    Returns:
        无。
    """
    await resume_tracker.clear_cancel(session_id)


async def purge_resume_jobs(session_id: str, *, exclude_job_id: str | None = None) -> list:
    """清理 arq 层指向该简历会话的所有残留僵尸 job（不依赖 worker 存活）。

    镜像 knowledge_space 的 ``purge_document_jobs``（doc574 同构缺口）：孤儿
    恢复此前只做 DB 手术+重入队，旧 job 的队列条目 / job 定义 / retry /
    in-progress 键无人清理——残留 job 被 worker 消费后会话被复活重跑，且与
    新 job 并发处理同一会话。

    Args:
        session_id: 简历会话主键（字符串形式）。
        exclude_job_id: 跳过该 job（孤儿恢复重入队场景下保护新 job）。

    Returns:
        被清理的 job_id 列表。
    """
    import pickle
    import time

    import arq.constants as arq_constants
    from novamind.shared.mq import get_arq_pool, get_queue_name

    pool = await get_arq_pool()
    queue_name = get_queue_name(pool)

    # 候选集 = tracker 绑定的 job（可能已不在队列、仅键残留）∪ 队列全量
    tracked_job_id = await get_job_id_for_resume(session_id)
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
            # 定义损坏的 job 无法校验归属，跳过（与 purge_document_jobs 同口径：
            # 宁可残留人工排查，不冒清错未知 job 的风险）
            from novamind.shared.logging import get_logger

            get_logger(__name__).warning(
                "残留 job 定义反序列化失败，跳过",
                session_id=session_id,
                job_id=job_id,
                error=str(e),
            )
            continue
        if job_def.get("f") != "process_resume_task":
            continue
        if (job_def.get("k") or {}).get("session_id") != session_id:
            continue

        # abort 信号：worker 存活且该 job 正在执行时可触发协作取消
        await pool.zadd(arq_constants.abort_jobs_ss, {job_id: now_ms})
        await pool.zrem(queue_name, job_id)
        await pool.delete(
            arq_constants.job_key_prefix + job_id,
            arq_constants.retry_key_prefix + job_id,
            arq_constants.in_progress_key_prefix + job_id,
        )
        purged.append(job_id)

    if purged:
        from novamind.shared.logging import get_logger

        get_logger(__name__).warning(
            "已清理简历会话残留 arq 僵尸 job",
            session_id=session_id,
            purged_job_ids=purged,
        )
    return purged

