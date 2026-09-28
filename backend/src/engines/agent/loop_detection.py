"""ReAct 循环检测：两层阈值，warn 次数注入提示引导收敛，hard_limit 次数强制结束循环；显著参数分桶只取关键字段 hash，防无关参数噪声误判。"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LoopDetectionConfig:
    """循环检测配置。"""

    enabled: bool = True
    warn_threshold: int = 3
    hard_limit: int = 5
    window: int = 20


# 显著参数字段（取这些字段做 hash，其余忽略）
_SIG_FIELDS = ("query", "command", "path", "url", "content", "code", "pattern", "cmd")


class LoopDetector:
    """单次 ReAct run 的循环检测器（per-run 状态，非线程共享）。"""

    def __init__(self, config: LoopDetectionConfig | None = None) -> None:
        """按配置初始化阈值与滑动窗口；窗口内计数，per-run 独立实例。"""
        cfg = config or LoopDetectionConfig()
        self._warn = cfg.warn_threshold
        self._hard = cfg.hard_limit
        self._history: deque[str] = deque(maxlen=cfg.window)
        self._warned: set[str] = set()

    def _stable_key(self, tool_name: str, args: dict[str, Any]) -> str:
        """显著参数分桶 hash。"""
        sig = {k: args[k] for k in _SIG_FIELDS if k in args}
        return f"{tool_name}:{json.dumps(sig, sort_keys=True, default=str)}"

    def track(
        self, tool_name: str, args: dict[str, Any]
    ) -> tuple[str | None, bool]:
        """记录一次工具调用，返回 (warning_message, should_hard_stop)。

        - ``warning_message`` 非 None 时，调用方应注入到 messages 提示模型
        - ``should_hard_stop`` True 时，调用方应 break ReAct 循环
        """
        key = self._stable_key(tool_name, args)
        self._history.append(key)
        count = self._history.count(key)

        if count >= self._hard:
            return (
                f"[FORCED STOP] 工具 {tool_name} 已重复调用 {count} 次，"
                "强制结束。请用已收集的结果给出最终答案。",
                True,
            )
        if count >= self._warn and key not in self._warned:
            self._warned.add(key)
            return (
                f"[LOOP DETECTED] 你正在重复调用 {tool_name}（相同参数 {count} 次）。"
                "停止重复调用工具，用已有结果给出最终答案。",
                False,
            )
        return None, False


__all__ = ["LoopDetectionConfig", "LoopDetector"]