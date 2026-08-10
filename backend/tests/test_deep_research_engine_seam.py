"""Deep Research 引擎接缝测试。

守护 deep_research 核心机制从 ``features/deep_research/services/`` 抽到
``engines/deep_research/`` 后的接缝不变式：

  - ``engines/deep_research/*.py`` 不得 import 宿主 ``features`` / ``setting`` /
    ORM 模型 / ``core.database`` / ``ModelConfigService``（端口化后 prompt 经注入
    ``PromptProvider``、LLM 客户端按调用注入、检索经 ``InternalSearchPort`` /
    ``WebSearchPort`` 注入、日志经注入 ``Logger``，切断引擎 -> 宿主导入边）。
  - ``EngineResearchParams`` 为纯 dataclass（无 Any / feature DTO）。
  - ``SearchSource`` 位于 ``engines/deep_research/types.py``，feature 侧 ORM 模型 /
    schemas / repository 经 re-export 反向引用（feature -> engine 合法）。
  - ``InternalSearchPort`` 协议位于 ``engines/deep_research/ports.py``，纯、不依赖 feature。
  - ``EngineInvalidResearchQueryError`` 位于 ``engines/deep_research/errors.py``。

A-1 阶段：仅守护纯模块子集（types/ports/errors/engine 纯函数 + 常量 + prompt key）。
A-2/A-3 阶段补充 ``DeepResearchEngine`` 方法签名与事件流断言。
"""
from __future__ import annotations

import ast
import importlib
import inspect
import sys
from dataclasses import fields
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit

# ---- deep_research 引擎侧模块 ----
_ENGINE_DR_MODULES = [
    "novamind.engines.deep_research.types",
    "novamind.engines.deep_research.ports",
    "novamind.engines.deep_research.errors",
    "novamind.engines.deep_research.engine",
]


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


def _source_tree(rel_path: str) -> ast.Module:
    src = (BACKEND_ROOT / rel_path).read_text(encoding="utf-8")
    return ast.parse(src)


@pytest.mark.parametrize("mod_name", _ENGINE_DR_MODULES)
def test_deep_research_engine_no_forbidden_imports(mod_name: str):
    """engines/deep_research/*.py 不得 import features/setting/ORM/core.database/ModelConfigService。"""
    mod = importlib.import_module(mod_name)
    imported = _imported_modules(mod)
    for imp in imported:
        assert not imp.startswith("novamind.features"), (
            f"{mod_name} 不得依赖 features: {imp}"
        )
        assert not imp.startswith("novamind.setting"), (
            f"{mod_name} 不得依赖 setting: {imp}"
        )
        assert imp != "novamind.core.database", (
            f"{mod_name} 不得 import core.database: {imp}"
        )
        assert imp != "novamind.core.database.database", (
            f"{mod_name} 不得 import core.database.database: {imp}"
        )
        assert "model_config_service" not in imp, (
            f"{mod_name} 不得 import ModelConfigService: {imp}"
        )


def test_engine_research_params_is_pure_dataclass():
    """EngineResearchParams 为纯 dataclass，字段全为原始类型（无 Any / feature DTO）。"""
    from novamind.engines.deep_research.types import EngineResearchParams

    forbidden_field_names = {"internal_config", "external_config", "llm_config", "research_mode"}
    field_names = {f.name for f in fields(EngineResearchParams)}
    for bad in forbidden_field_names:
        assert bad not in field_names, (
            f"EngineResearchParams 不应含 feature DTO 字段: {bad}"
        )
    # 必填核心字段
    expected = {
        "search_source", "depth", "iterations", "top_k",
        "external_max_results", "llm_max_tokens", "llm_temperature",
        "llm_top_p", "llm_model",
    }
    assert expected <= field_names, (
        f"EngineResearchParams 缺少字段: {expected - field_names}"
    )


def test_search_source_lives_in_engine_types():
    """SearchSource 定义在 engines/deep_research/types.py，feature 侧仅 re-export。"""
    from novamind.engines.deep_research.types import SearchSource as EngineSearchSource
    from novamind.features.deep_research.models import SearchSource as ModelSearchSource
    from novamind.features.deep_research.schemas import SearchSource as SchemaSearchSource

    # feature 侧 re-export 指向同一类对象
    assert ModelSearchSource is EngineSearchSource, (
        "models.SearchSource 应 re-export 自 engines.deep_research.types"
    )
    assert SchemaSearchSource is EngineSearchSource, (
        "schemas.SearchSource 应 re-export 自 engines.deep_research.types"
    )

    # ORM 模型文件本身不再定义 SearchSource 类
    model_src = (BACKEND_ROOT / "src/features/deep_research/models/research_session.py").read_text(
        encoding="utf-8"
    )
    assert "class SearchSource" not in model_src, (
        "models/research_session.py 不应再定义 SearchSource 类（已迁引擎层）"
    )


def test_internal_search_port_protocol_location():
    """InternalSearchPort 协议位于 engines/deep_research/ports.py，不依赖 feature。"""
    from novamind.engines.deep_research import ports as dr_ports

    imported = _imported_modules(dr_ports)
    for imp in imported:
        assert not imp.startswith("novamind.features"), (
            f"deep_research/ports.py 不应依赖 feature: {imp}"
        )
    assert hasattr(dr_ports, "InternalSearchPort")


def test_engine_invalid_research_query_error_location():
    """EngineInvalidResearchQueryError 位于 engines/deep_research/errors.py。"""
    from novamind.engines.deep_research.errors import EngineInvalidResearchQueryError

    assert issubclass(EngineInvalidResearchQueryError, Exception)


def test_engine_pure_functions_present_and_pure():
    """engine.py 暴露纯检索辅助函数与 prompt key 常量，无宿主依赖。"""
    from novamind.engines.deep_research import engine as dr_engine

    for name in (
        "should_use_external_search",
        "is_sufficient_results",
        "deduplicate_results",
        "extract_key_sources",
        "format_search_context",
    ):
        assert hasattr(dr_engine, name), f"engine.py 缺少纯函数: {name}"

    for key in (
        "KEY_ANALYZE_QUERY",
        "KEY_DECOMPOSE_TASKS",
        "KEY_SYNTHESIZE_REPORT",
        "KEY_SYNTHESIZE_REPORT_STREAM",
    ):
        assert hasattr(dr_engine, key), f"engine.py 缺少 prompt key 常量: {key}"

    # engine.py 不得 import features/setting/ORM
    imported = _imported_modules(dr_engine)
    for imp in imported:
        assert not imp.startswith(("novamind.features", "novamind.setting")), (
            f"engine.py 不应依赖 features/setting: {imp}"
        )


def test_search_event_variants_present():
    """SearchEvent 四变体（TaskStarted/IterationProgress/TaskFailed/SearchComplete）在 types.py。"""
    from novamind.engines.deep_research.types import (
        IterationProgress,
        SearchComplete,
        TaskFailed,
        TaskStarted,
    )

    for cls in (TaskStarted, IterationProgress, TaskFailed, SearchComplete):
        # dataclass
        assert hasattr(cls, "__dataclass_fields__"), f"{cls.__name__} 应为 dataclass"


def test_deep_research_service_reexports_search_source_from_engine():
    """service/repo/schemas 不再从 ORM 模型直接 import SearchSource（自引擎 re-export）。"""
    for rel in (
        "src/features/deep_research/services/deep_research_service.py",
        "src/features/deep_research/repository/research_repository.py",
        "src/features/deep_research/schemas/research_schema.py",
        "src/features/deep_research/schemas/__init__.py",
    ):
        tree = _source_tree(rel)
        # 收集所有 ImportFrom 中导入的 name
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "models.research_session" in node.module:
                for alias in node.names:
                    assert alias.name != "SearchSource", (
                        f"{rel} 仍从 models.research_session import SearchSource（应改自引擎 re-export）"
                    )