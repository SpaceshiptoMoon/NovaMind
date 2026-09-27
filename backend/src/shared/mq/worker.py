"""
arq 通用 Worker 运行时，提供嵌入式 Worker 的创建、启动与停止。
"""
import asyncio
from collections.abc import Callable, Sequence
from typing import Any

from arq.worker import Worker
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 全局 Worker 引用
_worker_task: asyncio.Task | None = None


async def create_embedded_worker(
    functions: Sequence[Callable],
    task_queue,
    cron_jobs: Sequence[dict[str, Any]] = (),
) -> Worker:
    """
    创建嵌入式 arq Worker

    Args:
        functions: arq 任务函数列表（由宿主装配点从各 feature ``tasks/`` 收集注入）
        task_queue: 宿主 ``task_queue`` 配置（queue_name/max_jobs/job_timeout/max_tries 等）
        cron_jobs: 周期任务列表（arq.cron 构造），空列表则不启用

    Returns:
        arq Worker 实例（需手动调用 worker.main()）
    """
    from novamind.shared.mq import get_arq_pool

    # 复用 ArqRedis 实例（包含 arq 特有方法如 enqueue_job）
    arq_pool = await get_arq_pool()

    worker_kwargs: dict[str, Any] = dict(
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
    if cron_jobs:
        worker_kwargs["cron_jobs"] = list(cron_jobs)

    worker = Worker(**worker_kwargs)

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
    cron_jobs: Sequence[dict[str, Any]] = (),
) -> asyncio.Task:
    """
    启动嵌入式 Worker 作为后台 asyncio.Task（带自愈重启）

    Args:
        functions: arq 任务函数列表（由宿主装配点注入）
        task_queue: 宿主 ``task_queue`` 配置
        cron_jobs: 周期任务列表（arq.cron 构造），空列表则不启用

    Returns:
        Worker 的 supervise asyncio.Task
    """
    global _worker_task

    _worker_task = asyncio.create_task(
        _supervise_worker(functions, task_queue, cron_jobs)
    )

    logger.info("嵌入式 arq Worker 已启动")
    return _worker_task


# Worker 异常退出后的重启退避基数（秒）：5 → 10 → 20 → 40 → 60 封顶，
# 防止 Redis 不可达等持续故障时无限刷重启日志。
_RESTART_BACKOFF_BASE_SECONDS = 5
_RESTART_BACKOFF_MAX_SECONDS = 60


async def _supervise_worker(
    functions: Sequence[Callable],
    task_queue,
    cron_jobs: Sequence[dict[str, Any]] = (),
) -> None:
    """Worker 监护循环：异常退出后指数退避重启。

    worker 异常退出（如 Redis 瞬断、连接池耗尽）若不自愈，所有文档任务
    将滞留队列直到整个进程重启（评审 P2-5）。取消（stop_embedded_worker）
    不重启；重启期间收到取消同样立即退出。
    """
    backoff = _RESTART_BACKOFF_BASE_SECONDS
    while True:
        worker = await create_embedded_worker(functions, task_queue, cron_jobs=cron_jobs)
        try:
            await _run_worker(worker)
            # 正常退出（CancelledError 在 _run_worker 内处理为取消语义）：
            # 视为显式停止，不再重启
            logger.info("arq Worker 已正常退出，监护循环结束")
            return
        except asyncio.CancelledError:
            logger.info("arq Worker 监护任务被取消，停止重启")
            raise
        except Exception as e:
            logger.error(
                "arq Worker 异常退出，将重启",
                error=str(e),
                restart_backoff_seconds=backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RESTART_BACKOFF_MAX_SECONDS)
        else:
            backoff = _RESTART_BACKOFF_BASE_SECONDS


async def _run_worker(worker: Worker) -> None:
    """运行 Worker（异常向上抛给监护循环决定重启）

    注意：必须调用 worker.main()（异步入口），而非 worker.run()（同步入口）。
    run() 内部会创建新事件循环，在已有事件循环中会抛出 "This event loop is already running"。
    """
    try:
        await worker.main()
    except asyncio.CancelledError:
        logger.info("arq Worker 收到取消信号，正在关闭...")
        await worker.close()
        raise
    except Exception as e:
        logger.error("arq Worker 异常退出", error=str(e))
        try:
            await worker.close()
        except Exception as close_err:
            logger.warning("arq Worker 关闭失败（继续重启流程）", error=str(close_err))
        raise


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