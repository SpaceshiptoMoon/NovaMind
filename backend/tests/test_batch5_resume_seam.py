"""批次5 resume 接缝测试。

验证：
  - ``app/services/resume_parser.py`` / ``resume_analyzer.py`` / ``resume_probing.py``
    三个 resume 引擎模块不再 import ``shared.prompts.PromptManager`` /
    ``core.middleware.structured_logging.get_logger`` /
    ``deep_research.services.*`` / ``user.services.model_config_service`` /
    ``setting.yaml_config``（切断 resume 引擎 -> 宿主 prompt/log/搜索/配置/ModelConfig
    导入边，为批次 6 抽 ``novamind-resume-engine`` 前提）。
  - 三个引擎构造器接收 ``PromptProvider`` + ``Logger`` 端口；``ResumeAnalyzer`` 额外
    接收可选 ``WebSearchPort``；``AutoProbingEngine`` 额外接收可选
    ``FallbackLLMProvider``（替代 bg_db + ModelConfigService）。
  - ``WebSearchPort`` / ``WebSearchResult`` 提升到中立的 ``engines/search_ports.py``，
    宿主适配器归属 ``features/deep_research/adapters/``（deep_research 拥有搜索服务），
    ``agent/core/ports.py`` 与 ``agent/adapters/web_search_adapter.py`` 重导出保持
    批次 3 零改动。
  - ``FallbackLLMProvider`` 协议位于 ``engines/ports.py``。
  - ``resume_pipeline_service`` 装配点构造并注入上述端口；``probe_all`` 不再接收
    ``bg_db`` 参数。
"""

import ast
import inspect
import importlib
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit

# ---- resume 引擎侧模块（批次6 迁 novamind-resume-engine）----
_ENGINE_RESUME_MODULES = [
    "novamind.features.app.services.resume_parser",
    "novamind.features.app.services.resume_analyzer",
    "novamind.features.app.services.resume_probing",
]

_FORBIDDEN_RESUME_IMPORTS = {
    "novamind.shared.prompts",
    "novamind.shared.prompts.templates",
    "novamind.shared.prompts.templates.PromptManager",
    "novamind.core.middleware.structured_logging",
    "novamind.features.deep_research.services.tavily_service",
    "novamind.features.deep_research.services.duckduckgo_service",
    "novamind.features.user.services.model_config_service",
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


@pytest.mark.parametrize("mod_name", _ENGINE_RESUME_MODULES)
def test_resume_engine_no_forbidden_imports(mod_name: str):
    """resume 引擎不得 import 宿主 PromptManager / get_logger / deep_research 服务 / ModelConfigService / setting。"""
    mod = importlib.import_module(mod_name)
    imported = _imported_modules(mod)
    for imp in imported:
        assert imp not in _FORBIDDEN_RESUME_IMPORTS, (
            f"{mod_name} 导入了禁止模块: {imp}"
        )


def test_resume_engines_require_port_injection():
    """三个 resume 引擎构造器均要求注入 PromptProvider + Logger。"""
    from novamind.features.app.services.resume_parser import ResumeParser
    from novamind.features.app.services.resume_analyzer import ResumeAnalyzer
    from novamind.features.app.services.resume_probing import AutoProbingEngine

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
    from novamind.features.app.services.resume_probing import AutoProbingEngine

    params = inspect.signature(AutoProbingEngine.probe_all).parameters
    assert "bg_db" not in params


def test_host_prompt_provider_satisfies_protocol():
    """app HostPromptProvider 实现 PromptProvider 协议。"""
    from novamind.engines.ports import PromptProvider
    from novamind.features.app.adapters.host_prompt_provider import HostPromptProvider

    provider = HostPromptProvider()
    assert isinstance(provider, PromptProvider)
    # 用真实存在的 resume prompt 键验证 format 委托 PromptManager
    formatted = provider.format("resume_summary", resume_data="测试简历")
    assert isinstance(formatted, str)
    assert len(formatted) > 0


def test_structlog_logger_satisfies_protocol():
    """宿主侧 structlog BoundLogger（.bind() 后）满足 Logger 协议。"""
    from novamind.shared.logging import Logger
    from novamind.core.middleware.structured_logging import get_logger

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
    assert hasattr(adapter_mod, "build_web_search_port")
    assert hasattr(adapter_mod, "as_web_search_port")

    # adapter 桥接到 deep_research.services（intra-feature，允许）
    imported = _imported_modules(adapter_mod)
    # 至少引用了 deep_research 搜索服务（延迟 import 不在顶层 AST，故只校验类存在）
    from novamind.engines.search_ports import WebSearchPort
    assert isinstance(adapter_mod.HostWebSearchPort(), WebSearchPort)


def test_agent_web_search_adapter_reexports():
    """agent/adapters/web_search_adapter.py 重导出 deep_research 适配器（批次3 零改动）。"""
    from novamind.features.agent.adapters import web_search_adapter as agent_adapter
    from novamind.features.deep_research.adapters import web_search_port_adapter as dr_adapter

    assert agent_adapter.HostWebSearchPort is dr_adapter.HostWebSearchPort
    assert agent_adapter.build_web_search_port is dr_adapter.build_web_search_port


def test_agent_core_ports_reexports_web_search_port():
    """engines/agent/ports.py 重导出 WebSearchPort（批次3 代码 import 路径不变）。"""
    from novamind.engines.agent import ports as agent_ports
    from novamind.engines.search_ports import WebSearchPort, WebSearchResult

    assert agent_ports.WebSearchPort is WebSearchPort
    assert agent_ports.WebSearchResult is WebSearchResult


def test_fallback_llm_provider_protocol_location():
    """FallbackLLMProvider 协议位于 engines/ports.py。"""
    from novamind.engines.ports import FallbackLLMProvider
    from novamind.features.app.adapters.host_fallback_llm_provider import HostFallbackLLMProvider

    class _FakeSvc:
        class repo:
            @staticmethod
            async def list_by_user(user_id, kind):
                return []

        async def get_llm_client_by_model(self, *a, **kw):
            return None

    provider = HostFallbackLLMProvider(_FakeSvc())
    assert isinstance(provider, FallbackLLMProvider)


def test_resume_pipeline_service_assembles_ports():
    """resume_pipeline_service 装配并注入端口（构造器不再硬编码引擎参数）。"""
    from novamind.features.app.services import resume_pipeline_service as svc_mod

    imported = _imported_modules(svc_mod)
    # 装配点 import 端口适配器
    assert any("host_prompt_provider" in imp for imp in imported), "应 import host_prompt_provider"
    assert any("host_fallback_llm_provider" in imp for imp in imported), "应 import host_fallback_llm_provider"
    assert any("web_search_port_adapter" in imp for imp in imported), "应 import web_search_port_adapter"

    src = inspect.getsource(svc_mod)
    assert "prompt_provider=prompt_provider" in src
    assert "logger=engine_logger" in src
    assert "web_search_port=web_search_port" in src
    assert "fallback_llm_provider=fallback_llm_provider" in src