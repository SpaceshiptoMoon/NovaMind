"""进程内管道计数器与 /metrics 端点测试（批次 5.3）。

覆盖：计数器累加与快照结构、未登记键自动登记、端点经 system manifest
挂载可达（/metrics 在 trace 中间件跳过清单内，不带 trace 开销）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.core.middleware import metrics as metrics_mod

pytestmark = pytest.mark.unit


@pytest.fixture()
def clean_counters():
    """快照前保存/恢复模块计数状态（测试间隔离）。"""
    saved = dict(metrics_mod._counters)
    metrics_mod._counters.clear()
    metrics_mod._counters.update({k: 0 for k in metrics_mod._COUNTER_HELP})
    yield
    metrics_mod._counters.clear()
    metrics_mod._counters.update(saved)


class TestCounters:
    def test_inc_and_snapshot(self, clean_counters):
        metrics_mod.inc("documents_completed", 3)
        metrics_mod.inc("documents_completed")
        snap = metrics_mod.snapshot()
        by_name = {c["name"]: c for c in snap["counters"]}
        assert by_name["documents_completed"]["value"] == 4
        assert by_name["documents_completed"]["help"] != ""

    def test_unknown_key_auto_registered(self, clean_counters):
        """未登记键自动登记（帮助信息缺失不影响计数）。"""
        metrics_mod.inc("custom_probe", 2)
        snap = metrics_mod.snapshot()
        by_name = {c["name"]: c for c in snap["counters"]}
        assert by_name["custom_probe"]["value"] == 2
        assert by_name["custom_probe"]["help"] == ""

    def test_endpoint_function_returns_snapshot(self, clean_counters):
        import asyncio

        metrics_mod.inc("tasks_enqueued", 5)
        result = asyncio.run(metrics_mod.pipeline_metrics())
        by_name = {c["name"]: c["value"] for c in result["counters"]}
        assert by_name["tasks_enqueued"] == 5


class TestMounted:
    def test_metrics_route_in_system_manifest(self):
        """/metrics 已挂进 system manifest（与 health 同级、无版本前缀）。"""
        manifest = __import__(
            "novamind.core.middleware.system_manifest", fromlist=["manifest"]
        ).manifest()
        keys = [spec.key for spec in manifest.routers]
        assert "metrics" in keys

    def test_metrics_in_trace_skip_prefixes(self):
        """/metrics 在 trace 中间件跳过清单内（高频抓取不带 trace 开销）。"""
        from novamind.core.middleware.trace_middleware import TraceIDMiddleware

        assert any("/metrics" in p for p in TraceIDMiddleware.SKIP_PATH_PREFIXES)
