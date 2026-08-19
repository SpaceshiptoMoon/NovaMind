"""ReAct 循环检测（E3 loop_detection）。

检测 Agent 重复调用相同工具（相同显著参数），防卡死：
- 第 1 层：相同 (tool_name + 显著参数) hash 在窗口内出现 ``warn_threshold`` 次 →
  向 messages 注入警告，提示模型停止重复调用、给出最终答案
- 第 2 层：出现 ``hard_limit`` 次 → 强制结束 ReAct 循环（进最终摘要）

显著参数分桶：只取 ``query/command/path/url/content/code`` 等关键字段做 hash，
避免无关参数噪声；附近行号/数值小差异不分桶（防 read_file 误判）。
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional, Set, Tuple


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

    def __init__(self, config: Optional[LoopDetectionConfig] = None) -> None:
        cfg = config or LoopDetectionConfig()
        self._warn = cfg.warn_threshold
        self._hard = cfg.hard_limit
        self._history: Deque[str] = deque(maxlen=cfg.window)
        self._warned: Set[str] = set()

    def _stable_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        """显著参数分桶 hash。"""
        sig = {k: args[k] for k in _SIG_FIELDS if k in args}
        return f"{tool_name}:{json.dumps(sig, sort_keys=True, default=str)}"

    def track(
        self, tool_name: str, args: Dict[str, Any]
    ) -> Tuple[Optional[str], bool]:
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