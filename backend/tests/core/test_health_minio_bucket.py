"""/health/detailed 的 minio 组件：业务桶未创建时的返回契约。

桶由后端首次写对象时懒创建，全新部署到首次上传之间必然不存在。锁定三个行为：
1. 桶未创建不是「连接失败」：组件报 degraded，error 说明是懒创建
2. 桶已创建时整体 healthy，minio 组件带 bucket_exists=True
3. 其余异常仍被笼统为「连接失败」，不在公开接口上暴露内部细节
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse
from novamind.core.middleware import health_check
from novamind.core.middleware.health_check import (
    ComponentNotReady,
    _check_minio_component,
    detailed_health_check,
)

pytestmark = pytest.mark.unit


class _FakeMinio:
    """get_minio_client 的替身，bucket_exists 按构造参数返回。"""

    def __init__(self, bucket_exists: bool) -> None:
        self._bucket_exists = bucket_exists

    async def bucket_exists(self, _name: str) -> bool:
        return self._bucket_exists


def _use_minio(monkeypatch: pytest.MonkeyPatch, *, bucket_exists: bool) -> None:
    async def _get_minio_client():
        return _FakeMinio(bucket_exists)

    monkeypatch.setattr(health_check, "get_minio_client", _get_minio_client)


def _patch_other_components(monkeypatch: pytest.MonkeyPatch, **overrides) -> None:
    """把 minio 之外的组件检查、配置与引擎读取全部打桩；overrides 按名称替换。"""
    async def _ok(*_args):
        return {}

    stubs = {
        "_check_db_component": _ok,
        "_check_redis_component": _ok,
        "_check_es_component": _ok,
        "_check_deepdoc_models_component": lambda: {"groups": {}},
        "_get_engine": lambda: object(),
        "cache_stats": lambda: {},
    }
    stubs.update(overrides)
    for name, stub in stubs.items():
        monkeypatch.setattr(health_check, name, stub)
    monkeypatch.setattr(
        health_check,
        "_get_config",
        lambda: SimpleNamespace(
            project=SimpleNamespace(version="test"),
            minio=SimpleNamespace(bucket_name="novamind"),
        ),
    )


def test_bucket_missing_raises_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """桶未创建 → 抛 ComponentNotReady（而非普通 Exception），文案点明懒创建。"""
    _use_minio(monkeypatch, bucket_exists=False)
    config = SimpleNamespace(minio=SimpleNamespace(bucket_name="novamind"))

    with pytest.raises(ComponentNotReady, match="自动创建"):
        asyncio.run(_check_minio_component(config))


def test_bucket_present_reports_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """桶已创建 → 返回 bucket_exists=True，不抛异常。"""
    _use_minio(monkeypatch, bucket_exists=True)
    config = SimpleNamespace(minio=SimpleNamespace(bucket_name="novamind"))

    assert asyncio.run(_check_minio_component(config)) == {"bucket_exists": True}


def test_missing_bucket_is_degraded_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """桶未创建走真实的 minio 检查：整体 degraded，minio 组件说明原因而非「连接失败」。"""
    _use_minio(monkeypatch, bucket_exists=False)
    _patch_other_components(monkeypatch)

    result = asyncio.run(detailed_health_check())

    assert not isinstance(result, JSONResponse)
    assert result["status"] == "degraded"
    assert result["components"]["minio"] == {
        "status": "degraded",
        "error": "业务桶未创建（首次上传文档时自动创建）",
    }
    assert result["components"]["database"]["status"] == "healthy"


def test_bucket_present_is_healthy_overall(monkeypatch: pytest.MonkeyPatch) -> None:
    """桶已创建且其余组件正常 → 整体 healthy。"""
    _use_minio(monkeypatch, bucket_exists=True)
    _patch_other_components(monkeypatch)

    result = asyncio.run(detailed_health_check())

    assert result["status"] == "healthy"
    assert result["components"]["minio"] == {"status": "healthy", "bucket_exists": True}


def test_other_failures_still_masked_as_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """非「未就绪」的异常仍笼统为「连接失败」，不把内部细节暴露到公开接口。"""
    async def _es_down():
        raise Exception("connect timeout: http://elasticsearch:9200 (internal detail)")

    _use_minio(monkeypatch, bucket_exists=True)
    _patch_other_components(monkeypatch, _check_es_component=_es_down)

    result = asyncio.run(detailed_health_check())

    assert isinstance(result, JSONResponse)
    assert result.status_code == 503
    body = json.loads(result.body)
    assert body["status"] == "unhealthy"
    assert body["components"]["elasticsearch"] == {"status": "unhealthy", "error": "连接失败"}
