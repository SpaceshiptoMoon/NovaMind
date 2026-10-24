"""快照总开关配置化测试（批次 6.4）。

``snapshots_enabled()`` 读 YAML ``knowledge_base.parsing.snapshots_enabled``：
- 配置关闭 → False（调用方跳过快照读写）；
- 配置读取失败（配置层异常/未初始化）→ True 兜底（快照是性能优化层，
  fail-open 保留续跑能力而非因配置故障禁用）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services import pipeline_snapshots

pytestmark = pytest.mark.unit


def _patch_config(monkeypatch, enabled: bool | None, raise_exc: bool = False):
    """monkeypatch get_config 返回带 parsing.snapshots_enabled 的假配置。"""
    from novamind.setting.yaml_config import loader as loader_mod

    if raise_exc:
        def _boom():
            raise RuntimeError("config not loaded")
        monkeypatch.setattr(loader_mod, "get_config", _boom)
        monkeypatch.setattr("novamind.setting.yaml_config.get_config", _boom)
        return
    cfg = SimpleNamespace(
        knowledge_base=SimpleNamespace(parsing=SimpleNamespace(snapshots_enabled=enabled))
    )
    monkeypatch.setattr(loader_mod, "get_config", lambda: cfg)
    monkeypatch.setattr("novamind.setting.yaml_config.get_config", lambda: cfg)


class TestSnapshotsEnabled:
    def test_config_off_returns_false(self, monkeypatch):
        _patch_config(monkeypatch, enabled=False)
        assert pipeline_snapshots.snapshots_enabled() is False

    def test_config_on_returns_true(self, monkeypatch):
        _patch_config(monkeypatch, enabled=True)
        assert pipeline_snapshots.snapshots_enabled() is True

    def test_config_failure_fails_open(self, monkeypatch):
        """配置读取失败按开启兜底（优化层故障不 disables 续跑能力）。"""
        _patch_config(monkeypatch, None, raise_exc=True)
        assert pipeline_snapshots.snapshots_enabled() is True
