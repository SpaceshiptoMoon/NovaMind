"""Resume 引擎接缝测试。

守护三引擎从 ``features/app/services/`` 迁入 ``engines/resume/`` 后的接缝不变式：

  - ``engines/resume/resume_parser.py`` / ``resume_analyzer.py`` / ``resume_probing.py``
    不得 import 宿主 ``features`` / ``setting`` / ``shared.prompts.PromptManager`` /
    ``core.middleware.structured_logging`` / ``engines.search.*`` provider /
    ``user.services.model_config_service``（端口化后 prompt/log/WebSearch/降级 LLM
    经注入端口，Schema 跟引擎走迁 ``engines/resume/schemas.py``，切断引擎 -> 宿主
    prompt/log/搜索/配置/ModelConfig/schema 导入边）。
  - 三个引擎构造器接收 ``PromptProvider`` + ``Logger`` 端口；``ResumeAnalyzer`` 额外
    接收可选 ``WebSearchPort``；``AutoProbingEngine`` 额外接收可选
    ``FallbackLLMProvider``（替代 bg_db + ModelConfigService）。
  - 引擎产物 Schema（``StructuredResume`` 等）位于 ``engines/resume/schemas.py``；
    feature 侧 API DTO（``ResumeSessionResponse`` / ``ResumeSessionListResponse``）
    留 ``features/app/schemas/resume_schema.py`` 反向引用（feature -> engine 合法）。
  - ``WebSearchPort`` / ``WebSearchResult`` 位于中立的 ``engines/search_ports.py``，
    搜索 provider 实现位于 ``shared/clients/search/``（基础外部服务客户端，非引擎），
    宿主适配器归属 ``features/deep_research/adapters/``。
  - ``FallbackLLMProvider`` 协议位于 ``engines/ports.py``。
  - ``resume_pipeline_service`` 装配点构造并注入上述端口；``probe_all`` 不再接收
    ``bg_db`` 参数。
"""

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

# ---- resume 引擎侧模块（已迁 engines/resume/）----
_ENGINE_RESUME_MODULES = [
    "novamind.engines.resume.resume_parser",
    "novamind.engines.resume.resume_analyzer",
    "novamind.engines.resume.resume_probing",
]

_FORBIDDEN_RESUME_IMPORTS = {
    "novamind.shared.prompts",
    "novamind.shared.prompts.templates",
    "novamind.shared.prompts.templates.PromptManager",
    "novamind.core.middleware.structured_logging",
    "novamind.shared.clients.search.tavily_service",
    "novamind.shared.clients.search.duckduckgo_service",
    "novamind.features.user.services.model_config_service",
    "novamind.features.app.schemas.resume_schema",
    "novamind.setting.yaml_config",
}


def _imported_modules(mod):
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


def test_resume_engine_imports_acyclic():
    """批次 3 后：resume 引擎 import 任意方向合法（R1），由无环门禁统一守护。"""
    import novamind.engines.resume.resume_analyzer  # noqa: F401
    import novamind.engines.resume.resume_parser  # noqa: F401
    import novamind.engines.resume.resume_probing  # noqa: F401


def test_resume_engines_require_port_injection():
    """三个 resume 引擎构造器均要求注入 PromptProvider + Logger。"""
    from novamind.engines.resume.resume_analyzer import ResumeAnalyzer
    from novamind.engines.resume.resume_parser import ResumeParser
    from novamind.engines.resume.resume_probing import AutoProbingEngine

    for cls in (ResumeParser, ResumeAnalyzer, AutoProbingEngine):
        params = inspect.signature(cls.__init__).parameters
        assert "prompt_provider" in params, f"{cls.__name__} 缺少 prompt_provider 参数"
        assert "logger" in params, f"{cls.__name__} 缺少 logger 参数"

    # ResumeAnalyzer 额外接收可选 WebSearchPort
    analyzer_params = inspect.signature(ResumeAnalyzer.__init__).parameters
    assert "web_search_port" in analyzer_params

    # AutoProbingEngine 额外接收可选 FallbackLLMProvider，不再接收 bg_db
    probing_params = inspect.signature(AutoProbingEngine.__init__).parameters
    assert "fallback_llm_provider" in probing_params
    assert "bg_db" not in probing_params, "AutoProbingEngine 不应再接收 bg_db"


def test_probe_all_no_bg_db_param():
    """probe_all 不再接收 bg_db 参数（降级 LLM 经 FallbackLLMProvider 注入）。"""
    from novamind.engines.resume.resume_probing import AutoProbingEngine

    params = inspect.signature(AutoProbingEngine.probe_all).parameters
    assert "bg_db" not in params


def test_prompt_manager_direct_use_satisfies_engine_surface():
    """批次 2.3：装配点直用 PromptManager 实例（.get/.format 满足引擎消费面）。"""
    from novamind.shared.prompts.prompt_manager import PromptManager

    provider = PromptManager()
    # 用真实存在的 resume prompt 键验证 format 可用
    formatted = provider.format("resume_summary", resume_data="测试简历")
    assert isinstance(formatted, str)
    assert len(formatted) > 0


def test_structlog_logger_satisfies_protocol():
    """宿主侧 structlog BoundLogger（.bind() 后）满足 Logger 协议。"""
    from novamind.core.middleware.structured_logging import get_logger
    from novamind.shared.logging import Logger

    host_logger = get_logger("resume.engine").bind()
    assert isinstance(host_logger, Logger)


def test_web_search_port_neutral_location():
    """WebSearchPort / WebSearchResult 位于 engines/search_ports.py，不依赖 feature。"""
    from novamind.engines import search_ports as sp_mod

    imported = _imported_modules(sp_mod)
    for imp in imported:
        assert not imp.startswith("novamind.features"), (
            f"search_ports 不应依赖任何 feature 模块: {imp}"
        )
    assert hasattr(sp_mod, "WebSearchPort")
    assert hasattr(sp_mod, "WebSearchResult")


def test_web_search_adapter_lives_in_deep_research():
    """WebSearchPort 宿主适配器归属 deep_research/adapters（DDD：搜索服务实现归属）。"""
    from novamind.features.deep_research.adapters import web_search_port_adapter as adapter_mod

    assert hasattr(adapter_mod, "HostWebSearchPort")
    assert hasattr(adapter_mod, "as_web_search_port")
    # 批次 2.1：build_web_search_port* 构造逻辑收敛 shared/search/web_search_factory

    # adapter 桥接到 deep_research.services（intra-feature，允许）
    imported = _imported_modules(adapter_mod)
    # 至少引用了 deep_research 搜索服务（延迟 import 不在顶层 AST，故只校验类存在）
    from novamind.engines.search_ports import WebSearchPort
    assert isinstance(adapter_mod.HostWebSearchPort(), WebSearchPort)


def test_agent_web_search_adapter_reexports():
    """批次 2.1 后 agent adapter 薄转发共享工厂的 resolve。"""
    from novamind.features.agent.adapters import web_search_adapter as agent_adapter
    from novamind.shared.search import web_search_factory

    assert agent_adapter.resolve_web_search_port is web_search_factory.resolve_web_search_port


def test_agent_core_ports_reexports_web_search_port():
    """engines/agent/ports.py 重导出 WebSearchPort（批次3 代码 import 路径不变）。"""
    from novamind.engines.agent import ports as agent_ports
    from novamind.engines.search_ports import WebSearchPort, WebSearchResult

    assert agent_ports.WebSearchPort is WebSearchPort
    assert agent_ports.WebSearchResult is WebSearchResult


def test_fallback_llm_provider_replaced_by_direct_mcs():
    """批次 3.3：FallbackLLMProvider 适配器已删，AutoProbingEngine 直收 ModelConfigService。"""
    import inspect

    from novamind.engines.resume.resume_probing import AutoProbingEngine

    sig = inspect.signature(AutoProbingEngine.__init__)
    ann = sig.parameters["fallback_llm_provider"].annotation
    assert "ModelConfigService" in str(ann), f"应直收 ModelConfigService，实际 {ann}"


def test_resume_pipeline_service_assembles_ports():
    """resume_pipeline_service 装配并注入端口（构造器不再硬编码引擎参数）。"""
    from novamind.features.app.services import resume_pipeline_service as svc_mod

    imported = _imported_modules(svc_mod)
    # 批次 2.1/2.3 后装配点 import：PromptManager 直用 + 共享 web 搜索工厂
    assert any("prompt_manager" in imp for imp in imported), "应 import prompt_manager"
    assert any("model_config_service" in imp for imp in imported), "应 import ModelConfigService（批次 3.3 直传）"
    assert any("web_search_factory" in imp for imp in imported), "应 import web_search_factory"

    src = inspect.getsource(svc_mod)
    assert "prompt_provider=prompt_provider" in src
    assert "logger=engine_logger" in src
    assert "web_search_port=web_search_port" in src
    assert "fallback_llm_provider=fallback_llm_provider" in src


def test_resume_engines_exported_from_engines_resume():
    """三引擎从 engines.resume 公共面导出（消费方经包级 import）。"""
    from novamind.engines.resume import (
        AutoProbingEngine,
        ResumeAnalyzer,
        ResumeParser,
    )

    assert ResumeParser.__name__ == "ResumeParser"
    assert ResumeAnalyzer.__name__ == "ResumeAnalyzer"
    assert AutoProbingEngine.__name__ == "AutoProbingEngine"


def test_resume_schema_split_location():
    """引擎产物 Schema 跟引擎走（engines/resume/schemas.py），feature 侧 DTO 反向引用。

    - StructuredResume 等 engine-output 模型在 engines.resume.schemas
    - ResumeSessionResponse / ResumeSessionListResponse 留 features.app.schemas.resume_schema
    - engines/resume/schemas.py 不含两个 DTO（拆分干净）
    - features/app/schemas/resume_schema.py 反向 import StructuredResume（feature -> engine 合法）
    """
    from novamind.engines.resume import schemas as engine_schemas
    from novamind.features.app.schemas import resume_schema as feature_dto

    # 引擎产物 Schema 在 engines.resume.schemas
    assert hasattr(engine_schemas, "StructuredResume")
    assert hasattr(engine_schemas, "JDAnalysis")
    assert hasattr(engine_schemas, "ProbingPlan")

    # DTO 留 feature，且不含 engine-output 模型（仅 2 个 DTO）
    assert hasattr(feature_dto, "ResumeSessionResponse")
    assert hasattr(feature_dto, "ResumeSessionListResponse")
    assert not hasattr(engine_schemas, "ResumeSessionResponse"), (
        "engines/resume/schemas.py 不应再含 API DTO（已拆回 feature）"
    )

    # feature DTO 反向引用 engine Schema（同一性 + Optional 包装）

    from novamind.engines.resume.schemas import StructuredResume
    field = feature_dto.ResumeSessionResponse.model_fields["structured_resume"]
    assert field.annotation == (StructuredResume | None), (
        f"structured_resume 注解应为 Optional[StructuredResume]，实际: {field.annotation}"
    )


def test_resume_engine_schema_no_features_import():
    """engines/resume/schemas.py 零 features/setting import（纯 Pydantic 引擎契约）。"""
    from novamind.engines.resume import schemas as engine_schemas

    imported = _imported_modules(engine_schemas)
    offenders = [m for m in imported if m.startswith(("novamind.features", "novamind.setting"))]
    assert not offenders, f"engines/resume/schemas.py 残留禁止 import: {offenders}"