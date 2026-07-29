"""批次5 evaluation 接缝测试：evaluator 经端口注入工作，不 import 业务侧 PromptManager/get_logger。

验证：
  - ``evaluation/services/{retrieval,generation,embedding}_evaluator.py`` 与
    ``claim_decomposer.py`` 不再 import ``shared.prompts.templates.PromptManager`` 或
    ``core.middleware.structured_logging.get_logger``（切断引擎 -> 宿主 prompt/log 导入边）。
  - 4 个 evaluator 经构造器接收 ``PromptProvider`` + ``Logger`` 端口（EmbeddingEvaluator 仅
    依赖注入的 ``BaseEmbedding``，无日志需求），且 ``HostPromptProvider`` 满足
    ``PromptProvider`` 协议、structlog BoundLogger 满足 ``Logger`` 协议。
  - ``EvaluationService`` 构造器接收 ``retrieval_port``/``retrieval_factory``/``session_factory``
    而非 ``search_service``，不再直接 import ``knowledge_space.services.search_service`` /
    ``shared.clients.get_elasticsearch_client`` / ``user.services.model_config_service``
    （这些装配下沉到 ``api/dependencies.py`` 宿主装配点）。
"""

import ast
import importlib
import inspect
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit

# ---- 引擎侧 evaluator 模块（批次6 迁 novamind-eval-engine）----
_ENGINE_EVAL_MODULES = [
    "novamind.features.evaluation.services.retrieval_evaluator",
    "novamind.features.evaluation.services.generation_evaluator",
    "novamind.features.evaluation.services.embedding_evaluator",
    "novamind.features.evaluation.services.claim_decomposer",
]

# evaluator 不得直接 import 业务侧 prompt 注册表 / 宿主结构化日志 / 宿主 features 旁路
_FORBIDDEN_EVAL_IMPORTS = {
    "novamind.shared.prompts.templates",
    "novamind.shared.prompts.templates.PromptManager",
    "novamind.core.middleware.structured_logging",
    "novamind.features.knowledge_space.services.search_service",
    "novamind.features.user.services.model_config_service",
}


def _imported_modules(mod):
    """AST 解析模块源码，提取所有 import 的模块名（避开 docstring/注释误报）。"""
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


@pytest.mark.parametrize("mod_name", _ENGINE_EVAL_MODULES)
def test_evaluator_no_forbidden_imports(mod_name: str):
    """evaluator 不得 import 业务侧 PromptManager / get_logger / cross-feature 服务。"""
    mod = importlib.import_module(mod_name)
    imported = _imported_modules(mod)
    for imp in imported:
        assert imp not in _FORBIDDEN_EVAL_IMPORTS, (
            f"{mod_name} 导入了禁止模块: {imp}"
        )


def test_host_prompt_provider_satisfies_protocol():
    """HostPromptProvider 实现 PromptProvider 协议（get/format）。"""
    from novamind.shared.engine_ports import PromptProvider
    from novamind.features.evaluation.adapters.host_prompt_provider import HostPromptProvider

    provider = HostPromptProvider()
    assert isinstance(provider, PromptProvider)
    # format 实际委托 PromptManager.format_prompt；用一个真实存在的 eval prompt 键验证
    formatted = provider.format(
        "eval_claim_decompose", generated_answer="测试回答"
    )
    assert isinstance(formatted, str)
    assert len(formatted) > 0


def test_structlog_logger_satisfies_protocol():
    """宿主侧 structlog BoundLogger 满足 Logger 协议（duck-type 兼容）。

    ``get_logger`` 返回 ``BoundLoggerLazyProxy``，首次调用方法时才绑定到真实
    ``BoundLogger``；``runtime_checkable`` Protocol 的 ``isinstance`` 对惰性代理
    会误判，故先 ``.bind()`` 触发绑定再校验。生产中 evaluator 调用 ``self._logger``
    的方法时同样会触发绑定。
    """
    from novamind.shared.engine_ports import Logger
    from novamind.core.middleware.structured_logging import get_logger

    host_logger = get_logger("evaluation.evaluators").bind()
    assert isinstance(host_logger, Logger)


def test_evaluators_require_port_injection():
    """4 个 evaluator 构造器均要求注入 PromptProvider + Logger（EmbeddingEvaluator 除外，仅 BaseEmbedding）。"""
    import inspect

    from novamind.features.evaluation.services.retrieval_evaluator import RetrievalEvaluator
    from novamind.features.evaluation.services.generation_evaluator import GenerationEvaluator
    from novamind.features.evaluation.services.claim_decomposer import ClaimDecomposer
    from novamind.features.evaluation.services.embedding_evaluator import EmbeddingEvaluator

    for cls in (RetrievalEvaluator, GenerationEvaluator, ClaimDecomposer):
        params = inspect.signature(cls.__init__).parameters
        assert "prompt_provider" in params, f"{cls.__name__} 缺少 prompt_provider 参数"
        assert "logger" in params, f"{cls.__name__} 缺少 logger 参数"

    # EmbeddingEvaluator 无日志/prompt 需求，只接 embedding_client
    emb_params = inspect.signature(EmbeddingEvaluator.__init__).parameters
    assert "embedding_client" in emb_params
    assert "prompt_provider" not in emb_params
    assert "logger" not in emb_params


def test_evaluation_service_uses_ports_and_factories():
    """EvaluationService 构造器接收 retrieval_port/retrieval_factory/session_factory，不再接收 search_service。"""
    import inspect

    from novamind.features.evaluation.services.evaluation_service import EvaluationService

    params = inspect.signature(EvaluationService.__init__).parameters
    assert "retrieval_port" in params, "EvaluationService 应接收 retrieval_port"
    assert "retrieval_factory" in params, "EvaluationService 应接收 retrieval_factory"
    assert "session_factory" in params, "EvaluationService 应接收 session_factory"
    assert "search_service" not in params, "EvaluationService 不应再接收 search_service"


def test_evaluation_service_no_cross_feature_imports():
    """evaluation_service 模块级 import 不得直接依赖 knowledge_space.services.search_service /
    shared.clients.get_elasticsearch_client / user.services.model_config_service（已下沉到 dependencies 装配点）。"""
    from novamind.features.evaluation.services import evaluation_service as svc_mod

    imported = _imported_modules(svc_mod)
    cross_feature_forbidden = {
        "novamind.features.knowledge_space.services.search_service",
        "novamind.features.user.services.model_config_service",
        "novamind.shared.clients",
    }
    for imp in imported:
        assert imp not in cross_feature_forbidden, (
            f"evaluation_service 模块级仍 import 了跨 feature 实现模块: {imp}"
        )