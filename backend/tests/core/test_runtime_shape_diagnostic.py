"""启动期运行形态诊断回归测试（_diagnose_runtime_shape）。

正例：workers=1（默认/缺失）不告警；反例：workers>1 按多 worker 部署告警并
指向单进程边界文档；环境变量非整数按 1 容错。
"""
import pytest
from novamind.core.middleware.app_factory import _WORKERS_ENV, _diagnose_runtime_shape

pytestmark = pytest.mark.unit


def _capture_warnings(monkeypatch):
    calls = []

    def _fake_warning(msg, **kwargs):
        calls.append((msg, kwargs))

    monkeypatch.setattr(
        "novamind.core.middleware.app_factory.logger.warning", _fake_warning
    )
    return calls


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
    calls = _capture_warnings(monkeypatch)

    _diagnose_runtime_shape()

    assert calls == []
