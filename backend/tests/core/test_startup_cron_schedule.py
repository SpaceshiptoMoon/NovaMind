"""回归门禁：kb-ops 归因 cron 调度必须为每 30 分钟（minute={0, 30}）。

根因回顾（2026-10-03 文档审计发现）：startup_manager 曾写
``cron(attribute_pending_events, minute=0, second=30)``——arq cron 的
``minute=0`` 只匹配第 0 分，实际每小时仅跑一次；而注释、loop 设计文档与
kb-ops-loop-summary 均声明「每 30 分钟」，意图与实现分裂长达两周未被发现。
归因批次回溯窗口为 7 天，降频不丢数据，但归因延迟翻倍、日级 KPI 口径漂移。

注册发生在应用启动的大函数内，调度参数无法低成本单测，故以源断言作回归
tripwire：任何人改回单分钟集（或误删该 cron）时本测试即刻红。
"""
import re
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit

_STARTUP_MANAGER = BACKEND_ROOT / "src" / "core" / "middleware" / "startup_manager.py"


def test_attribution_cron_fires_every_30_minutes():
    """归因 cron 的 minute 集必须为 {0, 30}，匹配「每 30 分钟」的文档口径。"""
    source = _STARTUP_MANAGER.read_text(encoding="utf-8")
    pattern = r"cron\(\s*attribute_pending_events\s*,\s*minute\s*=\s*\{\s*0\s*,\s*30\s*\}"
    assert re.search(pattern, source), (
        "attribute_pending_events 的 cron 未声明 minute={0, 30}："
        "单值 minute=0 会让归因从每 30 分钟降频为每小时一次（见模块 docstring 根因）"
    )
