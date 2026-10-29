"""切分器工厂 chunk_size 传导回归测试。

历史缺口：markdown/semantic 两策略的工厂装配只读引擎内部键
``max_chunk_size``，而 extract_splitting_params 会为缺失的该键补全局
默认（1000）——用户在 KB 配置的 ``chunk_size: 200`` 对这两策略静默
失效（切分策略实测矩阵暴露：配 200 实跑 1000，recursive 同配置生效）。
修复后统一经 _chunk_size_param：优先 chunk_size，回落 max_chunk_size。
"""
import pytest
from novamind.engines.document.pipeline.splitter_factory import (
    _chunk_size_param,
    build_splitter,
)

pytestmark = pytest.mark.unit


class _Deps:
    """semantic 策略装配所需的 embedding 依赖桩（构造期不调用）。"""

    embedding_client = object()


def _params(chunk_size=200, max_chunk_size=None):
    p = {"chunk_size": chunk_size}
    if max_chunk_size is not None:
        p["max_chunk_size"] = max_chunk_size
    return p


@pytest.mark.parametrize("strategy", ["markdown", "semantic"])
def test_chunk_size_reaches_markdown_and_semantic(strategy):
    """正例：用户 chunk_size 必须传导进 markdown/semantic 的块上限。"""
    splitter = build_splitter(strategy, _params(chunk_size=200), _Deps())
    assert splitter.max_chunk_size == 200


@pytest.mark.parametrize("strategy", ["markdown", "semantic"])
def test_max_chunk_size_still_honored_as_fallback(strategy):
    """兼容：显式传引擎内部键 max_chunk_size 仍生效（既有调用方不回退）。"""
    splitter = build_splitter(strategy, _params(chunk_size=None, max_chunk_size=500), _Deps())
    assert splitter.max_chunk_size == 500


@pytest.mark.parametrize("strategy", ["markdown", "semantic"])
def test_missing_both_falls_back_to_default(strategy):
    """两键皆缺时回落策略默认，不抛错。"""
    splitter = build_splitter(strategy, {}, _Deps())
    assert splitter.max_chunk_size > 0


def test_chunk_size_param_explicit_null_is_unconfigured():
    """显式 null 视同未配置（与全项目配置读取语义一致）。"""
    assert _chunk_size_param({"chunk_size": None, "max_chunk_size": None}, 1000) == 1000
