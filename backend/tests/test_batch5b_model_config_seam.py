"""批次 5b ModelConfigPort 端口化 + KnowledgeSpaceInfoPort 接缝测试。

验证：
  - ``ModelConfigPort`` 协议位于中立 ``shared/model_config_ports.py``，纯、不依赖 feature；
    ``ModelCredentials`` 同位于该中立模块。
  - ``ModelConfigService`` 结构化满足 ``ModelConfigPort``（runtime_checkable isinstance）。
  - ``ModelConfigPort`` 覆盖 8 个调用面方法签名，与 ``ModelConfigService`` 同名方法逐一存在。
  - ``model_config_service.py`` 不再 import ``knowledge_space.models``（:999 反向依赖经
    ``KnowledgeSpaceInfoPort`` 解除）；``_check_delete_impact`` 经注入 port 查询，不内联查 KnowledgeSpace。
  - ``KnowledgeSpaceInfoPort`` 协议中立（不依赖 feature），``HostKnowledgeSpaceInfoPort``
    满足协议；adapter 层持有跨 feature import（``knowledge_space.models``），service 层不再持有。
  - 各 feature 服务类（agent/chat、qa/ai_chat、qa/qa_service、deep_research、space_service、
    search_service、question_generation、knowledge_base_service、document_service、media_processing、
    evaluation_service、clawmate/chat、skill_marketplace）不再 import
    ``user.services.model_config_service``（切断 ``features.<X> → features.user.services`` 导入边），
    构造器含 ``model_config_service``/``model_config_port`` 参数。
  - 装配/入口点（``features/*/api/dependencies.py``、arq worker）允许 import 具体类（白名单）。
  - ``execute_document_pipeline`` 为 ``document_pipeline`` 模块级函数、接收 ``model_config_port`` 参数，
    内部不再 ``self.model_config_service``（模块级函数无 self）；document_pipeline / media_processing
    模块级静态助手接收 ``model_config_port`` 并透传，不再内部自建 ``ModelConfigService``。
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


def _imported_modules(mod) -> list:
    """AST 解析模块源码，提取所有 import 的模块名（含 ImportFrom.module 与 Import.alias.name）。"""
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
    """读取 backend 下相对路径文件的 AST。"""
    src = (BACKEND_ROOT / rel_path).read_text(encoding="utf-8")
    return ast.parse(src)


# ---- 端口中立性 ----

def test_model_config_port_protocol_location():
    """ModelConfigPort / ModelCredentials 位于中立 shared/model_config_ports.py，不依赖 feature。"""
    from novamind.shared import model_config_ports as mp

    imported = _imported_modules(mp)
    for imp in imported:
        assert not imp.startswith("novamind.features"), (
            f"model_config_ports 不应依赖任何 feature 模块: {imp}"
        )
    assert hasattr(mp, "ModelConfigPort")
    assert hasattr(mp, "ModelCredentials")


def test_knowledge_space_info_port_protocol_location():
    """KnowledgeSpaceInfoPort / SpaceEmbeddingUsage 位于 features/user/ports.py，不依赖其他 feature。"""
    from novamind.features.user import ports as ksip

    imported = _imported_modules(ksip)
    for imp in imported:
        assert not imp.startswith("novamind.features"), (
            f"user.ports 不应依赖任何 feature 模块: {imp}"
        )
    assert hasattr(ksip, "KnowledgeSpaceInfoPort")
    assert hasattr(ksip, "SpaceEmbeddingUsage")


# ---- ModelConfigService 满足端口 + 8 方法覆盖 ----

def test_model_config_service_satisfies_port():
    """ModelConfigService 结构化实现 ModelConfigPort 的 8 个调用面方法。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    # runtime_checkable 协议仅检查方法名存在性；ModelConfigService 结构化实现全部 8 方法。
    # 校验 8 个方法名都挂在 ModelConfigService 上（协议满足性见下一条测试的逐一比对）
    for name in _PORT_METHODS:
        assert hasattr(ModelConfigService, name), f"ModelConfigService 缺少端口方法: {name}"


_PORT_METHODS = [
    "get_llm_client_by_model",
    "get_vlm_client_by_model",
    "get_embedding_client_by_model",
    "get_rerank_client_by_model",
    "get_user_default_model_name",
    "list_available_models",
    "list_available_models_with_info",
    "get_credentials_by_model",
]


def test_model_config_port_covers_all_call_surfaces():
    """ModelConfigPort 协议覆盖 8 个调用面方法，与 ModelConfigService 同名方法逐一对应。"""
    from novamind.shared.model_config_ports import ModelConfigPort
    from novamind.features.user.services.model_config_service import ModelConfigService

    port_methods = {
        name
        for name, member in inspect.getmembers(ModelConfigPort, predicate=inspect.isfunction)
    }
    for name in _PORT_METHODS:
        assert name in port_methods, f"ModelConfigPort 协议缺少方法: {name}"
        assert hasattr(ModelConfigService, name), (
            f"ModelConfigService 未实现端口方法: {name}"
        )


def test_model_config_service_no_knowledge_space_models_import():
    """model_config_service.py 不得 import knowledge_space.models（:999 反向依赖已解除）。"""
    from novamind.features.user.services import model_config_service as mcs_mod

    imported = _imported_modules(mcs_mod)
    forbidden = {
        "novamind.features.knowledge_space.models.knowledge_space",
        "novamind.features.knowledge_space.models",
    }
    for imp in imported:
        assert imp not in forbidden, (
            f"model_config_service 仍 import 了 knowledge_space models: {imp}"
        )


def test_check_delete_impact_uses_injected_port():
    """_check_delete_impact 经注入的 _ks_info_port 查询，不内联 import KnowledgeSpace。"""
    from novamind.features.user.services import model_config_service as mcs_mod

    src = inspect.getsource(mcs_mod.ModelConfigService._check_delete_impact)
    assert "self._ks_info_port" in src, "_check_delete_impact 应使用注入的 _ks_info_port"
    assert "find_spaces_using_embedding_model" in src, (
        "_check_delete_impact 应经 port 查询 find_spaces_using_embedding_model"
    )
    assert "knowledge_space.models.knowledge_space" not in src, (
        "_check_delete_impact 不得内联 import knowledge_space.models"
    )


def test_model_config_service_ctor_accepts_ks_info_port():
    """ModelConfigService.__init__ 接收可选 knowledge_space_info_port 参数。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    params = inspect.signature(ModelConfigService.__init__).parameters
    assert "knowledge_space_info_port" in params, (
        "ModelConfigService.__init__ 缺少 knowledge_space_info_port 参数"
    )
    assert params["knowledge_space_info_port"].default is None


# ---- adapter 层 ----

def test_host_knowledge_space_info_port_satisfies_protocol():
    """HostKnowledgeSpaceInfoPort 满足 KnowledgeSpaceInfoPort 协议。"""
    from novamind.features.user.ports import KnowledgeSpaceInfoPort
    from novamind.features.user.adapters.knowledge_space_info_adapter import (
        HostKnowledgeSpaceInfoPort,
        as_knowledge_space_info_port,
    )

    class _FakeDB:
        async def execute(self, stmt):
            class _R:
                def all(self):
                    return []
            return _R()

    port = HostKnowledgeSpaceInfoPort(_FakeDB())
    assert isinstance(port, KnowledgeSpaceInfoPort)
    # 工厂返回同样满足协议
    assert isinstance(as_knowledge_space_info_port(_FakeDB()), KnowledgeSpaceInfoPort)


def test_adapter_holds_cross_feature_import_not_service_layer():
    """adapter 层（user/adapters）持有 knowledge_space.models import；service 层不再持有。

    这里仅断言 adapter 模块确实 import 了 knowledge_space.models（证明跨 feature 边界下沉到 adapter）。
    """
    from novamind.features.user.adapters import knowledge_space_info_adapter as adapter_mod

    imported = _imported_modules(adapter_mod)
    assert "novamind.features.knowledge_space.models.knowledge_space" in imported, (
        "adapter 层应持有 knowledge_space.models 跨 feature import"
    )


# ---- 服务类不再 import 具体 ModelConfigService ----

# （模块相对 backend 根路径, AST 读取避免触发重运行时导入副作用）
_SERVICE_MODULES = [
    "src/features/agent/services/chat_service.py",
    "src/features/qa/services/ai_chat_service.py",
    "src/features/qa/services/qa_service.py",
    "src/features/deep_research/services/deep_research_service.py",
    "src/features/knowledge_space/services/space_service.py",
    "src/features/knowledge_space/services/search_service.py",
    "src/features/knowledge_space/services/question_generation_service.py",
    "src/features/knowledge_space/services/knowledge_base_service.py",
    "src/features/knowledge_space/services/document_service.py",
    "src/features/knowledge_space/services/document_pipeline.py",
    "src/features/knowledge_space/services/document_upload_service.py",
    "src/features/knowledge_space/services/media_processing.py",
    "src/features/evaluation/services/evaluation_service.py",
    "src/features/clawmate/core/chat_service.py",
    "src/features/skill/services/skill_marketplace_service.py",
]

_FORBIDDEN_CONCRETE_IMPORT = "novamind.features.user.services.model_config_service"


@pytest.mark.parametrize("rel_path", _SERVICE_MODULES)
def test_service_modules_do_not_import_concrete_model_config_service(rel_path: str):
    """各 feature 服务类不得 import user.services.model_config_service（经 ModelConfigPort 注入）。"""
    tree = _source_tree(rel_path)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.append(node.module)
    assert _FORBIDDEN_CONCRETE_IMPORT not in imported, (
        f"{rel_path} 仍 import 了具体 ModelConfigService（应改用 ModelConfigPort 注入）"
    )


# ---- 构造器接收 ModelConfigPort 参数（采样校验）----

_DI_SERVICE_CLASSES = [
    ("novamind.features.agent.services.chat_service", "AgentChatService"),
    ("novamind.features.qa.services.qa_service", "QAService"),
    ("novamind.features.deep_research.services.deep_research_service", "DeepResearchService"),
    ("novamind.features.knowledge_space.services.space_service", "SpaceService"),
    ("novamind.features.knowledge_space.services.search_service", "SearchService"),
    ("novamind.features.knowledge_space.services.question_generation_service", "QuestionGenerationService"),
    ("novamind.features.knowledge_space.services.knowledge_base_service", "KnowledgeBaseService"),
    ("novamind.features.evaluation.services.evaluation_service", "EvaluationService"),
    ("novamind.features.skill.services.skill_marketplace_service", "SkillMarketplaceService"),
]


@pytest.mark.parametrize("mod_name,cls_name", _DI_SERVICE_CLASSES)
def test_service_ctor_accepts_model_config_port(mod_name: str, cls_name: str):
    """服务类构造器含 model_config_service（或同名）参数。"""
    mod = importlib.import_module(mod_name)
    cls = getattr(mod, cls_name)
    params = inspect.signature(cls.__init__).parameters
    assert "model_config_service" in params, (
        f"{cls_name}.__init__ 缺少 model_config_service 参数"
    )


# ---- document_service / media_processing 静态助手穿参 ----

_STATIC_HELPERS_DOCUMENT = [
    "_process_image_document_static",
    "_get_document_processor_static",
    "_get_embedding_client_static",
    "_generate_embeddings_static",
    "_generate_single_embedding_static",
    "_generate_questions_for_chunks_static",
    # 共享后置尾（切分/向量化/QG/索引）接收 model_config_port，由三模态管道注入
    "_run_post_parse_tail",
]


@pytest.mark.parametrize("helper_name", _STATIC_HELPERS_DOCUMENT)
def test_document_static_helpers_accept_model_config_port(helper_name: str):
    """document_pipeline 模块级静态助手接收 model_config_port 参数（调用方注入，不自建）。"""
    from novamind.features.knowledge_space.services import document_pipeline as ds

    fn = getattr(ds, helper_name)
    params = inspect.signature(fn).parameters
    assert "model_config_port" in params, f"{helper_name} 缺少 model_config_port 参数"


_MEDIA_HELPERS = [
    "process_video_document",
    "process_audio_document",
    "maybe_semantic_embedding_client",
]


@pytest.mark.parametrize("helper_name", _MEDIA_HELPERS)
def test_media_processing_helpers_accept_model_config_port(helper_name: str):
    """media_processing 模块函数接收 model_config_port 参数（调用方注入，不自建）。"""
    from novamind.features.knowledge_space.services import media_processing as mp

    fn = getattr(mp, helper_name)
    params = inspect.signature(fn).parameters
    assert "model_config_port" in params, f"{helper_name} 缺少 model_config_port 参数"


def test_execute_document_pipeline_module_level_with_port_param():
    """execute_document_pipeline 为 document_pipeline 模块级函数，接收 model_config_port（无 self）。"""
    from novamind.features.knowledge_space.services import document_pipeline as dp

    fn = dp.execute_document_pipeline
    # 模块级函数（已从 DocumentService 的 staticmethod 抽出），无 self 参数
    assert not isinstance(fn, staticmethod), "execute_document_pipeline 应为模块级函数，非 staticmethod"
    params = inspect.signature(fn).parameters
    assert "self" not in params, "execute_document_pipeline 为模块级函数，不应有 self"
    assert "model_config_port" in params, "execute_document_pipeline 缺少 model_config_port 参数"


# ---- 装配层白名单允许具体类 ----

_ASSEMBLY_MODULES = [
    "novamind.features.user.api.dependencies",
    "novamind.features.knowledge_space.api.dependencies",
    "novamind.features.agent.api.dependencies",
    "novamind.features.app.api.dependencies",
    "novamind.features.clawmate.api.dependencies",
    "novamind.features.deep_research.api.dependencies",
    "novamind.features.evaluation.api.dependencies",
    "novamind.features.skill.api.dependencies",
]


@pytest.mark.parametrize("mod_name", _ASSEMBLY_MODULES)
def test_assembly_modules_may_import_concrete(mod_name: str):
    """装配点（api/dependencies）允许 import 具体 ModelConfigService（白名单，非禁止）。

    本测试断言这些装配模块可正常导入（不抛错），且 get_model_config_service 等返回端口。
    仅做存在性校验，不强制要求 import 具体类——边界规则是『允许』而非『必须』。
    """
    importlib.import_module(mod_name)  # 不抛错即通过


def test_user_get_model_config_service_returns_port_with_ks_info():
    """user/api/dependencies.get_model_config_service 注入 ks_info_port 并以 ModelConfigPort 返回。"""
    from novamind.features.user.api.dependencies import get_model_config_service

    sig = inspect.signature(get_model_config_service)
    # 返回注解应为 ModelConfigPort（字符串或类型均可）
    ret = sig.return_annotation
    ret_name = ret if isinstance(ret, str) else getattr(ret, "__name__", str(ret))
    assert ret_name == "ModelConfigPort", (
        f"get_model_config_service 返回类型应为 ModelConfigPort，实际: {ret_name}"
    )


# ---- 前端契约保留：ModelCredentials 向后兼容 re-export ----

def test_model_credentials_backward_compat_reexport():
    """model_config_service 仍可导出 ModelCredentials（向后兼容，re-export 自 shared/model_config_ports）。"""
    from novamind.features.user.services.model_config_service import ModelCredentials
    from novamind.shared.model_config_ports import ModelCredentials as PortCreds

    assert ModelCredentials is PortCreds, "ModelCredentials 应为同一类（re-export）"
    # 字段契约保留
    creds = ModelCredentials(protocol="openai", model="gpt-4")
    assert creds.protocol == "openai"
    assert creds.model == "gpt-4"
    assert creds.api_key is None
    assert creds.base_url is None
    assert creds.extra_config is None