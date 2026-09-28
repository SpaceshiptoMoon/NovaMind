"""resume 域任务追踪（批次 6.4 从 shared/mq/task_tracker 下沉）。

resume 域函数归 app feature；通用 TaskTracker 类留 shared/mq。
resume_tracker 单例随迁（键名不变，Redis 数据兼容）。
"""
from novamind.shared.mq.task_tracker import resume_tracker


async def bind_job_to_resume(session_id: str, job_id: str) -> None:
    """绑定简历会话与 arq 任务 ID（供取消/状态查询定位任务）。"""
    await resume_tracker.bind(session_id, job_id)



async def get_job_id_for_resume(session_id: str) -> str | None:
    """查简历会话绑定的 arq 任务 ID，无绑定返回 None。"""
    return await resume_tracker.get_job_id(session_id)



async def unbind_resume_job(session_id: str) -> None:
    """解除简历会话的任务绑定（任务完结后调用）。"""
    await resume_tracker.unbind(session_id)



async def mark_resume_cancelled(session_id: str) -> None:
    """置简历会话取消标记，运行中的任务据此提前退出。"""
    await resume_tracker.mark_cancelled(session_id)



async def is_resume_cancelled(session_id: str) -> bool:
    """查询简历会话是否已被请求取消。"""
    return await resume_tracker.is_cancelled(session_id)



async def clear_resume_cancel_flag(session_id: str) -> None:
    """清除简历会话的取消标记（会话重置/复用时调用）。"""
    await resume_tracker.clear_cancel(session_id)

