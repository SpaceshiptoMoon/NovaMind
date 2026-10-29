"""解析质量报告：per-doc 结构化质量信息收集。

一次解析走了哪条路径、发生哪些降级/跳过、耗时多少——这些信息此前只散在
日志里，排障靠翻日志、下游无法程序化感知解析质量。本模块把解析期间当前
线程的 WARNING+ 日志捕获为结构化清单，随 DeepDocParseResult.metadata
的 quality 键出账。

线程限定：handler 挂在 root logger 上是进程全局，但 filter 按线程 id 收敛——
worker 并发解析（max_jobs>1）时各文档只收到自己线程内的记录，互不串话。
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

# 单文档警告上限：坏文档可能产生海量同类警告（逐形状/逐 sheet），封顶防
# 质量报告自身膨胀；截断计数在尾部注明
_WARNING_CAP = 50
_WARNING_MAX_CHARS = 300


class _ThreadWarningCollector(logging.Handler):
    """仅收集所属线程 WARNING+ 记录的 logging handler。"""

    def __init__(self, cap: int = _WARNING_CAP) -> None:
        """绑定创建线程并注册到 root logger 使用。"""
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []
        self._cap = cap
        self._tid = threading.get_ident()

    def filter(self, record: logging.LogRecord) -> bool:
        """只放行本线程的记录（并发解析隔离）。"""
        return record.thread == self._tid

    def emit(self, record: logging.LogRecord) -> None:
        """格式化并追加记录，超上限静默丢弃。"""
        if len(self.records) >= self._cap:
            return
        message = record.getMessage()
        if len(message) > _WARNING_MAX_CHARS:
            message = message[: _WARNING_MAX_CHARS - 3] + "..."
        self.records.append(f"{logging.getLevelName(record.levelno)}: {message}")


@contextmanager
def collect_warnings() -> Iterator[list[str]]:
    """捕获当前线程解析期间的 WARNING+ 日志为字符串列表。

    用法：
        with collect_warnings() as warnings:
            result = parser(...)
        # warnings 就地追加，解析结束后随 metadata["quality"] 出账
    """
    collector = _ThreadWarningCollector()
    root = logging.getLogger()
    root.addHandler(collector)
    try:
        yield collector.records
    finally:
        root.removeHandler(collector)


def build_quality_metadata(
    parser: str,
    warnings: list[str],
    started: float,
    **extra: object,
) -> dict[str, object]:
    """组装 metadata["quality"] 块（解析路径/警告/耗时 + 各格式特有字段）。"""
    quality: dict[str, object] = {
        "parser": parser,
        "warnings": list(warnings),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    quality.update(extra)
    return quality
