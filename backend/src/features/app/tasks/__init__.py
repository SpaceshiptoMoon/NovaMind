"""简历挖掘 arq 任务入口（宿主编排层）。

批次 6e 收口：本模块从 ``shared/mq/worker.py`` 下沉而来，承载简历挖掘 arq 任务的
宿主编排（执行 ResumePipelineService、失败兜底、孤儿恢复、入队）。任务函数经
``core/middleware/startup_manager`` 收集后注入 ``start_embedded_worker``。
"""
from novamind.features.app.tasks.resume_tasks import (
    enqueue_process_resume,
    process_resume_task,
    recover_orphan_resume_sessions,
)

__all__ = [
    "enqueue_process_resume",
    "process_resume_task",
    "recover_orphan_resume_sessions",
]