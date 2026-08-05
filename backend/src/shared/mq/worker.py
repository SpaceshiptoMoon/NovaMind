"""arq 通用 Worker 运行时（中立层）。

批次 6e 单向依赖收口：本模块只保留 arq 嵌入式 Worker 的通用运行时——创建/启动/
停止 Worker。宿主编排（任务函数、重试/取消兜底、孤儿恢复、入队）下沉到各 feature 的
``tasks/`` 子包，由 ``core/middleware/startup_manager`` 收集后经 ``functions`` 参数
注入本模块。``shared/mq`` 不得 import ``features`` 或 ``setting``。
"""
import asyncio
from typing import Callable, Optional, Sequence

from arq.worker import Worker

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 全局 Worker 引用
_worker_task: Optional[asyncio.Task] = None


async def create_embedded_worker(
    functions: Sequence[Callable],
    task_queue,
) -> Worker:
    """
    创建嵌入式 arq Worker

    Args:
        functions: arq 任务函数列表（由宿主装配点从各 feature ``tasks/`` 收集注入）
        task_queue: 宿主 ``task_queue`` 配置（queue_name/max_jobs/job_timeout/max_tries 等）

    Returns:
        arq Worker 实例（需手动调用 worker.main()）
    """
    from novamind.shared.mq import get_arq_pool

    # 复用 ArqRedis 实例（包含 arq 特有方法如 enqueue_job）
    arq_pool = await get_arq_pool()

    worker = Worker(
        functions=list(functions),
        redis_pool=arq_pool,
        queue_name=task_queue.queue_name,
        max_jobs=task_queue.max_jobs,
        job_timeout=task_queue.job_timeout,
        max_tries=task_queue.max_tries,
        ctx={
            "task_queue_max_tries": task_queue.max_tries,
            "retry_delay_seconds": task_queue.retry_base_delay,
        },
    )

    logger.info(
        "嵌入式 arq Worker 已创建",
        max_jobs=task_queue.max_jobs,
        job_timeout=task_queue.job_timeout,
        max_tries=task_queue.max_tries,
        retry_delay_seconds=task_queue.retry_base_delay,
        queue_name=task_queue.queue_name,
    )
    return worker


async def start_embedded_worker(
    functions: Sequence[Callable],
    task_queue,
) -> asyncio.Task:
    """
    启动嵌入式 Worker 作为后台 asyncio.Task

    Args:
        functions: arq 任务函数列表（由宿主装配点注入）
        task_queue: 宿主 ``task_queue`` 配置

    Returns:
        Worker 的 asyncio.Task
    """
    global _worker_task

    worker = await create_embedded_worker(functions, task_queue)
    _worker_task = asyncio.create_task(_run_worker(worker))

    logger.info("嵌入式 arq Worker 已启动")
    return _worker_task


async def _run_worker(worker: Worker) -> None:
    """运行 Worker（捕获异常，防止崩溃影响主服务）

    注意：必须调用 worker.main()（异步入口），而非 worker.run()（同步入口）。
    run() 内部会创建新事件循环，在已有事件循环中会抛出 "This event loop is already running"。
    """
    try:
        await worker.main()
    except asyncio.CancelledError:
        logger.info("arq Worker 收到取消信号，正在关闭...")
        await worker.close()
    except Exception as e:
        logger.error("arq Worker 异常退出", error=str(e))
        await worker.close()


async def stop_embedded_worker() -> None:
    """停止嵌入式 Worker"""
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
        logger.info("嵌入式 arq Worker 已停止")