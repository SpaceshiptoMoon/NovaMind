"""启动期运行形态诊断回归测试（_detect_worker_shape / _diagnose_runtime_shape）。

正例：workers=1（默认/缺失+主进程）不告警；反例：env>1 告警、CLI 多 worker
形态（env 缺失 + spawn 子进程名）告警；reload 开发子进程与伪造 env=1 不告警。
"""
import sys
from types import SimpleNamespace

import pytest
from novamind.core.middleware.app_factory import (
    _WORKERS_ENV,
    _detect_worker_shape,
    _diagnose_runtime_shape,
)

pytestmark = pytest.mark.unit


def _capture_warnings(monkeypatch):
    calls = []

    def _fake_warning(msg, **kwargs):
        calls.append((msg, kwargs))

    monkeypatch.setattr(
        "novamind.core.middleware.app_factory.logger.warning", _fake_warning
    )
    return calls


def _fake_spawn_process(monkeypatch, name="SpawnProcess-1"):
    monkeypatch.setattr(
        "multiprocessing.current_process", lambda: SimpleNamespace(name=name)
    )


def test_single_worker_no_warning(monkeypatch):
    monkeypatch.setenv(_WORKERS_ENV, "1")
    calls = _capture_warnings(monkeypatch)

    _diagnose_runtime_shape()

    assert calls == []


def test_env_missing_defaults_single_worker(monkeypatch):
    monkeypatch.delenv(_WORKERS_ENV, raising=False)
    calls = _capture_warnings(monkeypatch)

    _diagnose_runtime_shape()

    assert calls == []


def test_multi_worker_warns_with_doc_hint(monkeypatch):
    monkeypatch.setenv(_WORKERS_ENV, "4")
    calls = _capture_warnings(monkeypatch)

    _diagnose_runtime_shape()

    assert len(calls) == 1
    msg, kwargs = calls[0]
    assert "多 worker" in msg
    assert kwargs.get("workers") == 4
    assert "single-process-boundary-conventions" in kwargs.get("hint", "")


def test_bad_env_value_tolerated_as_single(monkeypatch):
    monkeypatch.setenv(_WORKERS_ENV, "not-a-number")
    _capture_warnings(monkeypatch)

    workers, source = _detect_worker_shape()

    assert (workers, source) == (1, "default")


# ==================== CLI/gunicorn 部署形态（env 缺失 + 进程探测） ====================


def test_cli_multi_worker_spawn_process_warns(monkeypatch):
    """uvicorn --workers / gunicorn 子进程（env 缺失 + 非 MainProcess）→ 告警"""
    monkeypatch.delenv(_WORKERS_ENV, raising=False)
    _fake_spawn_process(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["uvicorn", "main:create_app", "--factory"])
    calls = _capture_warnings(monkeypatch)

    _diagnose_runtime_shape()

    assert len(calls) == 1
    assert "疑似多进程" in calls[0][0]


def test_reload_child_process_not_warned(monkeypatch):
    """reload 开发子进程（argv 含 --reload）→ 不告警"""
    monkeypatch.delenv(_WORKERS_ENV, raising=False)
    _fake_spawn_process(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["main.py", "--reload"])
    calls = _capture_warnings(monkeypatch)

    _diagnose_runtime_shape()

    assert calls == []


def test_forged_env_one_suppresses_process_probe(monkeypatch):
    """env 显式为 1 时信任显式声明（伪造只影响日志真值，无安全后果）"""
    monkeypatch.setenv(_WORKERS_ENV, "1")
    _fake_spawn_process(monkeypatch)
    calls = _capture_warnings(monkeypatch)

    _diagnose_runtime_shape()

    assert calls == []


def test_main_process_env_missing_not_warned(monkeypatch):
    monkeypatch.delenv(_WORKERS_ENV, raising=False)
    _fake_spawn_process(monkeypatch, name="MainProcess")
    calls = _capture_warnings(monkeypatch)

    _diagnose_runtime_shape()

    assert calls == []
