"""进程内管道任务计数器与 /metrics 端点（批次 5.3 最小实现）。

单实例微模块：``get_pipeline_metrics()`` 返回进程内唯一计数器实例；
零外部依赖（不引 prometheus_client），JSON 形态输出，聚合到 Prometheus
等采集器由部署层抓取该端点完成。

计数是进程内的——多 worker 进程部署下各进程独立计数（/metrics 由各
进程分别暴露）；跨进程聚合属部署层职责，不在本模块范围。

不做什么：无历史序列、无直方图、无标签维度——最小可用面，先让吞吐/
失败率可见（此前生产只能靠日志和前端 5s 轮询肉眼观测）。
"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["指标"])

# 计数器登记（键 → 说明）；新计数器在此加一行，snapshot 自动带出说明
_COUNTER_HELP: dict[str, str] = {
    "tasks_enqueued": "文档处理任务入队数",
    "documents_completed": "文档处理成功终态数",
    "documents_failed": "文档处理失败终态数（含重试耗尽与永久错误）",
    "documents_cancelled": "文档处理被用户取消数",
    "retries_scheduled": "arq Retry 调度次数",
    "snapshot_parse_hits": "解析快照命中数（跳过昂贵解析）",
}

_lock = threading.Lock()
_counters: dict[str, int] = {key: 0 for key in _COUNTER_HELP}


def inc(counter: str, value: int = 1) -> None:
    """累加计数器；未登记的键自动登记（说明缺失仅影响 snapshot 的 help 字段）。"""
    with _lock:
        _counters[counter] = _counters.get(counter, 0) + value


def snapshot() -> dict[str, Any]:
    """当前计数快照（值 + 说明），供 /metrics 端点输出。"""
    with _lock:
        values = dict(_counters)
    return {
        "counters": [
            {"name": name, "value": values.get(name, 0), "help": _COUNTER_HELP.get(name, "")}
            for name in sorted(values)
        ],
    }


def get_pipeline_metrics() -> dict[str, Any]:
    """模块级便捷入口（与单例语义一致：计数器即模块状态）。"""
    return snapshot()


@router.get("/metrics")
async def pipeline_metrics() -> dict[str, Any]:
    """管道任务计数指标（JSON；进程内口径，多 worker 部署由部署层聚合）。"""
    return snapshot()
