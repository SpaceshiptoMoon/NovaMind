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


# ---- A-2：DeepResearchEngine LLM 方法按调用接 client/provider ----


def test_deep_research_engine_methods_present():
    """DeepResearchEngine 暴露 analyze_query/decompose_tasks/synthesize_report/synthesize_report_stream。"""
    from novamind.engines.deep_research.engine import DeepResearchEngine

    for name in (
        "analyze_query",
        "decompose_tasks",
        "synthesize_report",
        "synthesize_report_stream",
    ):
        assert hasattr(DeepResearchEngine, name), (
            f"DeepResearchEngine 缺少 LLM 方法: {name}"
        )


def test_deep_research_engine_llm_methods_accept_llm_and_prompt_provider():
    """analyze_query/decompose_tasks/synthesize_report[_stream] 按调用接 llm_client + prompt_provider（AgentEngine 风格）。"""
    from novamind.engines.deep_research.engine import DeepResearchEngine
    from novamind.shared.ai_models.llm import BaseLLM
    from novamind.engines.ports import PromptProvider

    for name in ("analyze_query", "decompose_tasks", "synthesize_report", "synthesize_report_stream"):
        fn = getattr(DeepResearchEngine, name)
        params = inspect.signature(fn).parameters
        # 首参 self（unbound method），次参 llm_client（位置），再次 prompt_provider（位置）；其余 keyword-only
        param_list = [p for p in params.values() if p.name != "self"]
        assert param_list[0].name == "llm_client", (
            f"{name} 首参（除 self）应为 llm_client，实际: {param_list[0].name}"
        )
        assert param_list[1].name == "prompt_provider", (
            f"{name} 次参应为 prompt_provider，实际: {param_list[1].name}"
        )


def test_deep_research_engine_decompose_tasks_takes_depth_int():
    """decompose_tasks 接 depth（int），不接 ResearchMode（feature DTO）。"""
    from novamind.engines.deep_research.engine import DeepResearchEngine

    fn = DeepResearchEngine.decompose_tasks
    params = inspect.signature(fn).parameters
    assert "depth" in params, "decompose_tasks 应接 depth 参数"
    # 不应有 research_mode 参数
    assert "research_mode" not in params, (
        "decompose_tasks 不应接 research_mode（feature DTO，引擎不感知业务枚举）"
    )


def test_deep_research_engine_synthesize_report_derives_context_internally():
    """synthesize_report 接 results（在引擎内 format_search_context），不接预格式化 context。

    与 synthesize_report_stream（接预格式化 context）非对称：stream 路径在 feature 调用前已格式化。
    """
    from novamind.engines.deep_research.engine import DeepResearchEngine

    fn = DeepResearchEngine.synthesize_report
    params = inspect.signature(fn).parameters
    assert "results" in params, "synthesize_report 应接 results 参数（引擎内派生 context）"
    # 非流式不应接预格式化 context（应自 results 派生）
    assert "context" not in params, (
        "synthesize_report 不应接预格式化 context（应在引擎内自 results 派生）"
    )

    # 流式接预格式化 context（非对称，调用方已格式化）
    stream_fn = DeepResearchEngine.synthesize_report_stream
    stream_params = inspect.signature(stream_fn).parameters
    assert "context" in stream_params, (
        "synthesize_report_stream 应接预格式化 context（stream 路径调用前已格式化）"
    )


def test_deep_research_engine_ctor_no_business_context():
    """DeepResearchEngine.__init__ 不接 ResearchContext / ORM / repo（仅可选 logger）。"""
    from novamind.engines.deep_research.engine import DeepResearchEngine

    params = inspect.signature(DeepResearchEngine.__init__).parameters
    # 仅 self + logger（keyword-only）
    param_names = set(params.keys()) - {"self"}
    assert param_names == {"logger"}, (
        f"DeepResearchEngine.__init__ 应仅接 logger，实际: {param_names}"
    )
    assert params["logger"].kind == inspect.Parameter.KEYWORD_ONLY, (
        "logger 应为 keyword-only"
    )


def test_deep_research_service_proxies_llm_methods():
    """service 的 _analyze_query/_decompose_tasks/_synthesize_report[_stream] 薄委托 DeepResearchEngine。

    service 方法仍保留原签名（调用点不变），体内 sanitize + 取 llm + 委托 engine。
    """
    from novamind.features.deep_research.services.deep_research_service import DeepResearchService

    for name in ("_analyze_query", "_decompose_tasks", "_synthesize_report", "_synthesize_report_stream"):
        assert hasattr(DeepResearchService, name), (
            f"DeepResearchService 缺少薄委托方法: {name}"
        )

    # service 构造器装配了 engine + prompt_provider
    service_src = inspect.getsource(DeepResearchService)
    assert "self._engine" in service_src, "service 应装配 self._engine"
    assert "self._prompt_provider" in service_src, "service 应装配 self._prompt_provider"
    assert "DeepResearchEngine(" in service_src, "service 应构造 DeepResearchEngine 实例"


def test_deep_research_service_maps_engine_error_to_feature_error():
    """E2：service 在 research/research_stream 边界捕获 EngineInvalidResearchQueryError → InvalidResearchQueryError。"""
    service_src = (
        BACKEND_ROOT / "src/features/deep_research/services/deep_research_service.py"
    ).read_text(encoding="utf-8")

    assert "EngineInvalidResearchQueryError" in service_src, (
        "service 应 import EngineInvalidResearchQueryError 用于边界映射"
    )
    # research() 与 research_stream() 均应有 except EngineInvalidResearchQueryError 分支
    # 统计出现次数：import 1 + research 1 + research_stream 1 = 3
    assert service_src.count("except EngineInvalidResearchQueryError") >= 2, (
        "research() 与 research_stream() 均应捕获 EngineInvalidResearchQueryError（>=2 处）"
    )
    assert "raise InvalidResearchQueryError(str(e))" in service_src, (
        "应将 EngineInvalidResearchQueryError 映射为 InvalidResearchQueryError"
    )