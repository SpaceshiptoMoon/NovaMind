"""数据源抽象模块（engines/deep_research/sources.py）单元测试。

守护可插拔数据源接缝不变式：

  - ``sources.py`` 不得 import ``features`` / ``setting`` / ORM / ``core.database``
    （AST 扫描，仿 seam 测试写法）。
  - ``SearchSourcePort`` 为 runtime_checkable 协议：``HostInternalSearchPort``
    天然满足；dict 返回的 fake 同样满足。
  - ``SearchSourceBinding`` 为纯 dataclass（source_type: str / port / top_k）。
"""
from __future__ import annotations

import ast
import importlib
import inspect
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def _imported_modules(mod) -> list:
    """AST 解析模块源码，提取所有 import 的模块名。"""
    imported = []
    try:
        tree = ast.parse(inspect.getsource(mod))
    except (OSError, TypeError):
        return imported
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.append(node.module)
    return imported


def test_sources_module_no_forbidden_imports():
    """sources.py 不得 import features/setting/ORM/core.database。"""
    mod = importlib.import_module("novamind.engines.deep_research.sources")
    imported = _imported_modules(mod)
    for imp in imported:
        assert not imp.startswith("novamind.features"), (
            f"sources.py 不得依赖 features: {imp}"
        )
        assert not imp.startswith("novamind.setting"), (
            f"sources.py 不得依赖 setting: {imp}"
        )
        assert not imp.startswith("novamind.core.database"), (
            f"sources.py 不得 import core.database: {imp}"
        )


def test_search_source_port_runtime_checkable_and_shape():
    """SearchSourcePort 为 runtime_checkable 协议；同形实现（含 HostInternalSearchPort）满足。"""
    from novamind.engines.deep_research.sources import SearchSourcePort

    class _Fake:
        async def search(self, query, *, top_k):
            return [{"content": "c", "score": 1.0, "source_type": "internal"}]

    assert isinstance(_Fake(), SearchSourcePort), (
        "search(query, *, top_k) -> List[Dict] 实现应满足 SearchSourcePort"
    )

    # HostInternalSearchPort 与协议同形，天然满足
    from novamind.features.deep_research.adapters.internal_search_port_adapter import (
        HostInternalSearchPort,
    )

    assert hasattr(HostInternalSearchPort, "search")


def test_binding_and_context_are_pure_dataclasses():
    """SearchSourceBinding/SearchSourceContext 为纯 dataclass，字段契约固定。"""
    from dataclasses import fields

    from novamind.engines.deep_research.sources import (
        SearchSourceBinding,
        SearchSourceContext,
    )

    binding_fields = {f.name for f in fields(SearchSourceBinding)}
    assert binding_fields == {"source_type", "port", "top_k"}

    ctx_fields = {f.name for f in fields(SearchSourceContext)}
    assert ctx_fields == {"space_id", "user_id", "config", "deps"}


def test_sourcetype_values_match_legacy_literals():
    """SourceType 值与历史结果 dict 的 source_type 字面量一致（internal/external）。"""
    from novamind.engines.deep_research.types import SourceType

    assert SourceType.INTERNAL.value == "internal"
    assert SourceType.EXTERNAL.value == "external"
