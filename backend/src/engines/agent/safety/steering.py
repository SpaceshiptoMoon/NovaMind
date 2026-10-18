"""运行中插话队列（steering）：agent 执行期间用户消息经此排队，在 ReAct 轮边界注入。

对标 pi 的 steering inbox 思想的最小化——per-connection 的 asyncio.Queue 薄封装，
不做持久化（插话会作为 user 消息经 chat_service 正常落库，队列只是运行中的
中转）。引擎在每轮迭代顶部 drain，注入点语义：本轮工具已跑完、下一轮 LLM 调用
之前，模型能看到插话后调整方向。
"""
from __future__ import annotations

import asyncio

from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class SteeringQueue:
    """单次 WS 连接的插话队列（per-connection，非线程共享）。"""

    def __init__(self, maxsize: int = 8) -> None:
        """初始化有界队列；上限防恶意刷屏撑爆内存，满后拒绝并告警。"""
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)

    def put(self, content: str) -> bool:
        """用户插话入队；队列满时丢弃并返回 False（fail-safe：不阻塞 WS 接收循环）。"""
        text = (content or "").strip()
        if not text:
            return False
        try:
            self._queue.put_nowait(text)
            return True
        except asyncio.QueueFull:
            logger.warning("steering 队列已满，插话被丢弃", dropped_len=len(text))
            return False

    def drain(self) -> list[str]:
        """非阻塞取走当前全部插话（引擎轮边界调用）；空队列返回 []。"""
        items: list[str] = []
        while True:
            try:
                items.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                return items

    def empty(self) -> bool:
        """报告队列是否为空（引擎快速路径免 drain 开销）。"""
        return self._queue.empty()


__all__ = ["SteeringQueue"]
