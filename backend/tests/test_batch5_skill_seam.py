"""批次5 skill + AgentRegistryPort 接缝测试。

验证：
  - ``skill/services/skill_checker.py`` 与 ``skill/services/skill_parser.py`` 不再 import
    ``shared.prompts.templates.PromptManager`` 或 ``core.middleware.structured_logging.get_logger``
    （切断 skill 引擎 -> 宿主 prompt/log 导入边，为批次6 抽 ``novamind-skill-engine`` 前提）。
  - ``SkillSecurityChecker`` 构造器接收可选 ``prompt_provider`` + ``logger`` 端口，且默认
    无 LLM 行为保持不变（``check_llm`` 在未注入 LLM 或 prompt_provider 时返回 None）。
  - ``extract_skill_zip`` 接收可选 ``logger`` 端口参数。
  - ``SkillMarketplaceService`` 构造器接收 ``agent_registry_port``，install/uninstall/list_installed
    经端口访问 Agent，不再接收 ``agent_repository`` 参数。
  - ``skill_marketplace_service`` 模块级不再 import ``agent.repository.agent_repository`` 或
    ``agent.api.exceptions``（skill -> agent 服务层导入边已断）。
  - ``AgentRegistryPort`` 协议位于中立 ``shared/registry_ports.py``，宿主适配器
    ``HostAgentRegistryPort`` 满足协议。
  - 前端契约保留：``SkillTargetAgentNotFoundError`` code=``AGENT_NOT_FOUND``，且在 skill
    异常处理器 ``status_map`` 中映射 404（否则落入 SkillError:500）。
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

# ---- skill 引擎侧模块（批次6 迁 novamind-skill-engine）----
_ENGINE_SKILL_MODULES = [
    "novamind.features.skill.services.skill_checker",
    "novamind.features.skill.services.skill_parser",
]

_FORBIDDEN_SKILL_IMPORTS = {
    "novamind_engine_core.prompts.templates",
    "novamind_engine_core.prompts.templates.PromptManager",
    "novamind_engine_core.prompts",
    "novamind.core.middleware.structured_logging",
    # skill 引擎侧不得直接依赖 agent feature（经 AgentRegistryPort 注入）
    "novamind.features.agent.repository.agent_repository",
    "novamind.features.agent.api.exceptions",
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


@pytest.mark.parametrize("mod_name", _ENGINE_SKILL_MODULES)
def test_skill_engine_no_forbidden_imports(mod_name: str):
    """skill 引擎侧（skill_checker / skill_parser）不得 import 业务侧 PromptManager / get_logger / agent feature。"""
    mod = importlib.import_module(mod_name)
    imported = _imported_modules(mod)
    for imp in imported:
        assert imp not in _FORBIDDEN_SKILL_IMPORTS, (
            f"{mod_name} 导入了禁止模块: {imp}"
        )


def test_skill_checker_optional_port_injection():
    """SkillSecurityChecker 构造器接收可选 prompt_provider + logger（关键字参数，默认 None）。"""
    from novamind.features.skill.services.skill_checker import SkillSecurityChecker

    params = inspect.signature(SkillSecurityChecker.__init__).parameters
    assert "prompt_provider" in params, "SkillSecurityChecker 缺少 prompt_provider 参数"
    assert "logger" in params, "SkillSecurityChecker 缺少 logger 参数"
    # 保持默认无 LLM 行为：未注入 prompt_provider 时 check_llm 返回 None
    checker = SkillSecurityChecker()
    assert checker._prompt_provider is None
    assert checker._logger is None


@pytest.mark.asyncio
async def test_skill_checker_check_llm_none_without_llm():
    """默认无 LLM 时 check_llm 返回 None（行为不变）。"""
    from novamind.features.skill.services.skill_checker import SkillSecurityChecker

    checker = SkillSecurityChecker()
    result = await checker.check_llm("malicious body", "---\nname: x\n---")
    assert result is None


@pytest.mark.asyncio
async def test_skill_checker_check_llm_none_without_prompt_provider():
    """有 LLM 但未注入 prompt_provider 时 check_llm 仍返回 None（不触碰 PromptManager）。"""
    from novamind.features.skill.services.skill_checker import SkillSecurityChecker

    class _StubLLM:
        async def generate_text(self, *args, **kwargs):
            raise AssertionError("不应在缺 prompt_provider 时调用 LLM")

    checker = SkillSecurityChecker(llm_client=_StubLLM())
    result = await checker.check_llm("body", "frontmatter")
    assert result is None


def test_skill_parser_extract_zip_logger_param():
    """extract_skill_zip 接收可选 logger 参数。"""
    from novamind.features.skill.services.skill_parser import extract_skill_zip

    params = inspect.signature(extract_skill_zip).parameters
    assert "logger" in params, "extract_skill_zip 缺少 logger 参数"
    # logger 默认 None
    assert params["logger"].default is None


def test_skill_marketplace_service_uses_agent_registry_port():
    """SkillMarketplaceService 构造器接收 agent_registry_port，install/uninstall 不再接收 agent_repository。"""
    from novamind.features.skill.services.skill_marketplace_service import SkillMarketplaceService

    ctor_params = inspect.signature(SkillMarketplaceService.__init__).parameters
    assert "agent_registry_port" in ctor_params, "构造器应接收 agent_registry_port"

    install_params = inspect.signature(SkillMarketplaceService.install_skill).parameters
    assert "agent_registry_port" not in install_params
    assert "agent_repository" not in install_params, "install_skill 不应再接收 agent_repository"

    uninstall_params = inspect.signature(SkillMarketplaceService.uninstall_skill).parameters
    assert "agent_repository" not in uninstall_params, "uninstall_skill 不应再接收 agent_repository"


def test_skill_marketplace_service_no_agent_imports():
    """skill_marketplace_service 模块级不得 import agent.repository / agent.api.exceptions（经端口访问）。"""
    from novamind.features.skill.services import skill_marketplace_service as svc_mod

    imported = _imported_modules(svc_mod)
    forbidden = {
        "novamind.features.agent.repository.agent_repository",
        "novamind.features.agent.api.exceptions",
    }
    for imp in imported:
        assert imp not in forbidden, (
            f"skill_marketplace_service 模块级仍 import 了 agent 实现模块: {imp}"
        )


def test_agent_registry_port_protocol_location():
    """AgentRegistryPort 协议位于中立的 shared/registry_ports.py，纯、无 feature 导入。"""
    from novamind.shared import registry_ports as rp_mod

    imported = _imported_modules(rp_mod)
    for imp in imported:
        assert not imp.startswith("novamind.features"), (
            f"registry_ports 不应依赖任何 feature 模块: {imp}"
        )
    assert hasattr(rp_mod, "AgentRegistryPort")
    assert hasattr(rp_mod, "AgentSummary")


def test_host_agent_registry_port_satisfies_protocol():
    """HostAgentRegistryPort 满足 AgentRegistryPort 协议。"""
    from novamind_engine_core.registry_ports import AgentRegistryPort
    from novamind.features.agent.adapters.agent_registry_adapter import HostAgentRegistryPort

    class _FakeRepo:
        async def get_by_id(self, agent_id):
            return None

        async def update(self, agent_id, **kwargs):
            return None

    port = HostAgentRegistryPort(_FakeRepo())
    assert isinstance(port, AgentRegistryPort)


def test_skill_target_agent_not_found_preserves_contract():
    """SkillTargetAgentNotFoundError 逐字保留前端契约：code=AGENT_NOT_FOUND。"""
    from novamind.features.skill.exceptions import SkillTargetAgentNotFoundError

    err = SkillTargetAgentNotFoundError(123)
    assert err.code == "AGENT_NOT_FOUND"
    assert "123" in err.message


def test_skill_exception_handler_maps_404():
    """SkillTargetAgentNotFoundError 必须在 skill 异常处理器 status_map 显式映射 404。

    Starlette 最具体类匹配优先：若不显式映射 404，该异常（SkillError 子类）会落入
    SkillError:500 处理器，返回 500 而非 404，破坏前端契约。
    """
    from novamind.features.skill.api import exception_handlers as eh

    src = inspect.getsource(eh.setup_skill_exception_handlers)
    assert "SkillTargetAgentNotFoundError: 404" in src, (
        "skill 异常处理器 status_map 必须显式映射 SkillTargetAgentNotFoundError -> 404"
    )