"""解析任务流的独立 worker 消费循环：认领门控 / 心跳 / Retry→延迟重派 / 终态 XACK。

与 arq 嵌入式 worker 的职责分工（backend 切换由 task_queue.backend 决定）：
- arq 模式：API 进程内嵌入式 worker 消费 arq:queue 队列
- stream 模式：本模块消费 nm:parse:tasks 流（独立进程，可与 API 分离部署）

消息信封只含 ID + 派发参数（process_mode/retry_count/trace_id）；配置快照
等状态数据在任务行 document_task_items 上——认领门控（CAS + 心跳）是
取消/幂等/防双消费的统一收口，不依赖消息幂等。

投递语义：at-least-once——消费者崩溃后消息留 PEL，由 reaper 按心跳过期
重派；防双消费靠 CAS 门控（SQL 行级原子）+ 管道三级指纹（重复执行成本
由快照兜底）。不追求 exactly-once。
"""
import asyncio
import signal
from typing import Any

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# 心跳刷新间隔与 TTL——TTL = 刷新间隔 × 3 倍余量（防单次 GC/网络抖动误判）
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_TTL_SECONDS = 90

# 死任务判定：PROCESSING 且心跳消失超过此时长（秒）才视为消费者崩溃
STALE_THRESHOLD_SECONDS = 300

_SIGNALS = (signal.SIGTERM, signal.SIGINT)


async def run_parse_consumer(stop_event: asyncio.Event) -> None:
    """解析任务流消费主循环（阻塞运行直到 stop_event 触发）。

    启动初始化链（config/加密/ClientFactory/Redis/prompt 注册）由调用方
    （parse_worker.py 入口）完成后传入——本函数只做消费循环。
    """
    from novamind.setting.yaml_config import get_config
    from novamind.shared.mq import get_arq_pool
    from novamind.shared.mq.stream_queue import ensure_parse_group, xreadgroup_parse

    cfg = get_config().task_queue
    consumer = f"parse-worker-{id(asyncio.current_task()) % 10000}"
    block_ms = cfg.parse_block_ms
    max_concurrent = max(1, cfg.parse_max_concurrency)

    pool = await get_arq_pool()
    await ensure_parse_group(pool)

    in_flight: set[asyncio.Task] = set()
    logger.info(
        "解析 stream 消费循环启动",
        consumer=consumer,
        max_concurrent=max_concurrent,
        block_ms=block_ms,
    )

    async def _wait_stop() -> None:
        await stop_event.wait()

    loop = asyncio.get_running_loop()
    stop_task = loop.create_task(_wait_stop())

    try:
        while not stop_event.is_set():
            try:
                messages = await xreadgroup_parse(pool, consumer, 1, block_ms)
            except Exception as exc:
                logger.warning("stream 消费读取异常（退避后重试）", error=str(exc))
                await asyncio.sleep(1)
                continue

            for message_id, payload in messages:
                if stop_event.is_set() or len(in_flight) >= max_concurrent:
                    # 停机中/并发满：消息留 PEL 由 reaper 重派
                    break
                task_id = payload.get("task_id")
                if task_id is None:
                    from novamind.shared.mq.stream_queue import xack_parse

                    await xack_parse(pool, message_id)
                    logger.warning("消息缺 task_id，XACK 丢弃", message_id=str(message_id))
                    continue

                t = asyncio.create_task(
                    _execute_message(pool, message_id, payload)
                )
                in_flight.add(t)
                t.add_done_callback(in_flight.discard)

        # 优雅停机：等全部在飞任务完成
        if in_flight:
            logger.info("优雅停机：等待在飞任务完成", count=len(in_flight))
            await asyncio.gather(*in_flight, return_exceptions=True)
    finally:
        stop_task.cancel()


async def _execute_message(pool, message_id: str, payload: dict[str, Any]) -> None:
    """执行单条消息：CAS 认领门控 → 心跳 + 管道执行 → 终态 XACK。

    process_document_task 内部已处理全部错误分流（终态标记/重试标记/
    降级/通知），本函数只做认领门控与 arq.Retry 的延迟重派映射。
    """
    from novamind.features.knowledge_space.tasks.document_tasks import (
        process_document_task,
    )
    from novamind.setting.yaml_config import get_config
    from novamind.shared.mq.stream_queue import xack_parse

    task_id = payload["task_id"]
    document_id = payload["document_id"]
    kb_id = payload["kb_id"]
    space_id = payload["space_id"]
    retry_count = payload.get("retry_count", 0)
    trace_id = payload.get("trace_id")

    cfg = get_config().task_queue

    # ---- 1. CAS 认领门控（取消/幂等/防双消费/超限的统一收口） ----
    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.models.document_task import (
        DocumentTask,
        TaskStatus,
    )
    from sqlalchemy import update

    async with get_db_session() as gate_session:
        result = await gate_session.execute(
            update(DocumentTask)
            .where(
                DocumentTask.id == task_id,
                DocumentTask.status.in_([TaskStatus.PENDING, TaskStatus.FAILED]),
                DocumentTask.retry_count < cfg.max_tries,
            )
            .values(status=TaskStatus.PROCESSING)
        )
        await gate_session.commit()
        if result.rowcount == 0:
            logger.info(
                "任务不可认领（已取消/双消费/超限），XACK 丢弃",
                task_id=task_id, message_id=message_id,
            )
            await xack_parse(pool, message_id)
            return

    # ---- 2. 心跳 + 管道执行 ----
    hb_task = asyncio.create_task(_heartbeat_loop(task_id, pool))
    try:
        ctx = {
            "job_id": message_id,
            "job_try": retry_count + 1,
            "task_queue_max_tries": cfg.max_tries,
            "retry_delay_seconds": cfg.retry_base_delay,
        }
        await process_document_task(
            ctx,
            document_id=document_id,
            kb_id=kb_id,
            space_id=space_id,
            trace_id=trace_id,
        )
        await xack_parse(pool, message_id)
    except Exception as exc:
        # process_document_task 内部的 _ensure_mark_terminal 已写终态；
        # 此处只 XACK（消息已处理完毕——终态在任务行上，不可重复消费）
        logger.error(
            "stream 消息执行异常（终态已由内部标记）",
            task_id=task_id, message_id=message_id, error=str(exc),
        )
        await xack_parse(pool, message_id)
    finally:
        hb_task.cancel()


async def _heartbeat_loop(task_id: int, pool) -> None:
    """周期刷新心跳键（证明消费者存活），执行结束自动退出。"""
    from novamind.shared.mq.stream_queue import parse_heartbeat_key

    key = parse_heartbeat_key(task_id)
    try:
        while True:
            await pool.set(key, "1", ex=HEARTBEAT_TTL_SECONDS)
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning("心跳刷新异常（终态标记靠 reaper 兜底）", task_id=task_id, error=str(e))


async def run_reaper(stop_event: asyncio.Event, pool) -> None:
    """reaper：扫 PROCESSING 且心跳过期的任务 → 重派或终判（每分钟一轮）。

    补上现有"仅启动时恢复"的缺口：白天 crash 的任务不再搁浅到下次重启。
    """
    from novamind.core.database.database import get_db_session
    from novamind.features.knowledge_space.repository.document_task_repository import (
        DocumentTaskRepository,
    )
    from novamind.setting.yaml_config import get_config
    from novamind.shared.mq.stream_queue import (
        parse_heartbeat_key,
        xack_parse,
        xadd_parse_task,
    )

    cfg = get_config().task_queue
    interval = cfg.parse_reaper_interval
    max_tries = cfg.max_tries

    while not stop_event.is_set():
        try:
            async with get_db_session() as session:
                repo = DocumentTaskRepository(session)
                stale = await repo.list_processing_tasks()
                for task in stale:
                    key = parse_heartbeat_key(task.id)
                    if await pool.exists(key):
                        continue  # 心跳在，活消费者持有

                    old_message_id = task.job_id
                    if old_message_id:
                        await xack_parse(pool, old_message_id)

                    task.retry_count = (task.retry_count or 0) + 1
                    if task.retry_count >= max_tries:
                        await _mark_failed(session, task.id, "reaper: 超过最大重试次数")
                        logger.warning("任务重试超限，终判 FAILED", task_id=task.id)
                    else:
                        await xadd_parse_task(pool, {
                            "task_id": task.id,
                            "document_id": task.document_id,
                            "kb_id": task.kb_id,
                            "space_id": task.space_id,
                            "process_mode": int(task.process_mode or 0),
                            "retry_count": task.retry_count,
                        })
                        logger.info("任务重派", task_id=task.id, retry_count=task.retry_count)
                await session.commit()
        except Exception as exc:
            logger.warning("reaper 轮次异常（下轮重试）", error=str(exc))

        await _sleep_or_stop(stop_event, interval)


async def _mark_failed(session, task_id: int, error_message: str) -> None:
    """终判 FAILED（独立会话已由调用方管理）。"""
    from novamind.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
    from novamind.shared.utils.time_utils import now_china

    task = await session.get(DocumentTask, task_id)
    if task:
        task.status = TaskStatus.FAILED
        task.error_message = error_message
        task.completed_at = now_china()
        await session.flush()


async def _sleep_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    """可中断 sleep：stop_event 触发时提前返回。"""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def run_delayed_dispatcher(stop_event: asyncio.Event) -> None:
    """延迟搬运协程：定期取 nm:parse:delayed 到期条目 XADD 回主流。"""
    from novamind.shared.mq import get_arq_pool
    from novamind.shared.mq.stream_queue import pop_due_delayed

    pool = await get_arq_pool()
    while not stop_event.is_set():
        try:
            payloads = await pop_due_delayed(pool, limit=20)
            for payload in payloads:
                from novamind.shared.mq.stream_queue import xadd_parse_task

                await xadd_parse_task(pool, payload)
        except Exception as exc:
            logger.warning("延迟搬运轮次异常", error=str(exc))
        await _sleep_or_stop(stop_event, 5)
