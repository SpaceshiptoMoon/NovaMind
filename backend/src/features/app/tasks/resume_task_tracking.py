"""resume 域任务追踪（批次 6.4 从 shared/mq/task_tracker 下沉）。

resume 域函数归 app feature；通用 TaskTracker 类留 shared/mq。
resume_tracker 单例随迁（键名不变，Redis 数据兼容）。
"""
from novamind.shared.mq.task_tracker import resume_tracker


async def bind_job_to_resume(session_id: str, job_id: str) -> None:
    await resume_tracker.bind(session_id, job_id)



async def get_job_id_for_resume(session_id: str) -> str | None:
    return await resume_tracker.get_job_id(session_id)



async def unbind_resume_job(session_id: str) -> None:
    await resume_tracker.unbind(session_id)



async def mark_resume_cancelled(session_id: str) -> None:
    await resume_tracker.mark_cancelled(session_id)



async def is_resume_cancelled(session_id: str) -> bool:
    return await resume_tracker.is_cancelled(session_id)



async def clear_resume_cancel_flag(session_id: str) -> None:
    await resume_tracker.clear_cancel(session_id)

