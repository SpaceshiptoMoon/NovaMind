"""解析任务流的 Redis Stream 封装（派发层从 arq 迁移的基础设施）。

职责边界：本模块只做 Stream 原语的薄封装（XADD/消费组读取/ACK/认领/
延迟 zset/心跳键），**不含业务语义**——认领门控、执行、重试决策在
消费侧（parse_stream_consumer）。与 arq 队列的关系由
``TaskQueueConfig.backend`` 决定（arq | stream），两者并存互不影响。

键约定：
- 流：``nm:parse:tasks``（XADD 带 MAXLEN 近似修剪，防无限增长）
- 消费组：``parse-workers``（多 worker 实例 = 消费组内竞争消费）
- 延迟 zset：``nm:parse:delayed``（score = 到期毫秒时间戳）
- 心跳：``nm:heartbeat:{task_id}``（TTL 见配置，执行期间周期续期）
"""
import json
import time
from typing import Any

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

PARSE_STREAM_KEY = "nm:parse:tasks"
PARSE_STREAM_GROUP = "parse-workers"
PARSE_DELAYED_KEY = "nm:parse:delayed"

# XADD 近似修剪上限：ACK 后条目仍留在 stream 里（XACK 只动 PEL），
# 靠 MAXLEN 兜底防无限增长；10 万条 × ~2KB ≈ 200MB 上界，可调
PARSE_STREAM_MAXLEN = 100_000

_STREAM_FIELD = "payload"


def parse_heartbeat_key(task_id: int) -> str:
    """执行心跳键（任务行 status=PROCESSING 期间的存活证明）。"""
    return f"nm:heartbeat:{task_id}"


def _dump_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _load_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


async def xadd_parse_task(pool, payload: dict[str, Any]) -> str:
    """派发任务信封到解析流，返回 stream message id。

    MAXLEN 近似修剪：ACK 不删条目，无修剪则流无限增长；~100 万条上界
    内的历史消息由 Redis 惰性删除节点回收。
    """
    return await pool.xadd(
        PARSE_STREAM_KEY,
        {_STREAM_FIELD: _dump_payload(payload)},
        maxlen=PARSE_STREAM_MAXLEN,
        approximate=True,
    )


async def ensure_parse_group(pool) -> None:
    """幂等创建消费组（MKSTREAM 空流也建组；BUSYGROUP 视为已存在）。"""
    try:
        await pool.xgroup_create(
            PARSE_STREAM_KEY, PARSE_STREAM_GROUP, id="0-0", mkstream=True
        )
    except Exception as exc:  # noqa: BLE001 redis-py 抛 ResponseError(BUSYGROUP)
        if "BUSYGROUP" not in str(exc):
            raise


async def xreadgroup_parse(pool, consumer: str, count: int, block_ms: int) -> list[tuple[str, dict[str, Any]]]:
    """从消费组读新消息（> 语义：只取从未投递给本组的条目）。

    Returns:
        [(message_id, payload dict), ...]；BLOCK 超时返回空列表。
    """
    result = await pool.xreadgroup(
        PARSE_STREAM_GROUP,
        consumer,
        {PARSE_STREAM_KEY: ">"},
        count=count,
        block=block_ms,
    )
    if not result:
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    for _stream, entries in result:
        for message_id, fields in entries:
            raw = fields.get(_STREAM_FIELD) if isinstance(fields, dict) else None
            if raw is None and isinstance(fields, (list, tuple)):
                # redis-py decode_responses=False 时 fields 是 [(k, v), ...]
                raw = next((v for k, v in fields if k == _STREAM_FIELD), None)
            try:
                out.append((message_id, _load_payload(raw)))
            except Exception as e:  # 载荷损坏：跳过并告警，不阻塞消费循环
                logger.warning(
                    "stream 消息载荷解析失败，跳过",
                    message_id=str(message_id),
                    error=str(e),
                )
    return out


async def xack_parse(pool, message_id: str) -> int:
    """终态确认（work-completed ack：只在任务终态后调用）。"""
    return await pool.xack(PARSE_STREAM_KEY, PARSE_STREAM_GROUP, message_id)


async def xclaim_stalled(
    pool, consumer: str, min_idle_ms: int, count: int
) -> list[tuple[str, dict[str, Any]]]:
    """认领其他死消费者遗留的 PEL 条目（心跳过期的死任务由调用方判定）。"""
    result = await pool.xautoclaim(
        PARSE_STREAM_KEY, PARSE_STREAM_GROUP, consumer,
        min_idle_time=min_idle_ms, start_id="0-0", count=count,
    )
    # redis-py xautoclaim 返回 (next_start_id, entries, deleted_ids)
    entries = result[1] if isinstance(result, tuple) else []
    out: list[tuple[str, dict[str, Any]]] = []
    for message_id, fields in entries:
        raw = fields.get(_STREAM_FIELD) if isinstance(fields, dict) else None
        if raw is None and isinstance(fields, (list, tuple)):
            raw = next((v for k, v in fields if k == _STREAM_FIELD), None)
        try:
            out.append((str(message_id), _load_payload(raw)))
        except Exception as e:
            logger.warning(
                "stream 认领消息载荷解析失败，跳过",
                message_id=str(message_id),
                error=str(e),
            )
    return out


# ==================== 延迟 zset（arq _defer_by 的替代） ====================


def _now_ms() -> int:
    return int(time.time() * 1000)


async def zadd_delayed(pool, payload: dict[str, Any], delay_seconds: float) -> None:
    """延迟派发：到期后由搬运协程 XADD 回主流（替代 arq _defer_by）。"""
    due = _now_ms() + int(delay_seconds * 1000)
    await pool.zadd(PARSE_DELAYED_KEY, {_dump_payload(payload): due})


async def pop_due_delayed(pool, limit: int = 20) -> list[dict[str, Any]]:
    """取出全部到期的延迟消息（zrangebyscore + zrem 原子性由调用侧单消费者保证）。"""
    due = _now_ms()
    raws = await pool.zrangebyscore(PARSE_DELAYED_KEY, "-inf", due, start=0, num=limit)
    if not raws:
        return []
    payloads: list[dict[str, Any]] = []
    for raw in raws:
        raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        await pool.zrem(PARSE_DELAYED_KEY, raw)
        try:
            payloads.append(json.loads(raw_str))
        except Exception as e:
            logger.warning("延迟消息反序列化失败，丢弃", raw=raw_str[:100], error=str(e))
    return payloads
