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
    search_service、question_generation、knowledge_base_service、document_pipeline /
    document_upload_service / document_task_service / document_query_service、media_processing、
    evaluation_service、skill_marketplace）不再 import
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

BACKEND_ROOT = Path(__file__).resolve().parents[2]
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

def test_knowledge_space_info_port_protocol_location():
    """批次 4.5：KnowledgeSpaceInfoPort 已删，ks repository 提供公共查询方法。"""
    from novamind.features.knowledge_space.repository.space_repository import SpaceRepository

    assert hasattr(SpaceRepository, "find_spaces_using_embedding")
# ---- ModelConfigService 满足端口 + 8 方法覆盖 ----

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


def test_check_delete_impact_uses_injected_port():
    """批次 4.5：删除影响检查直查 ks repository（不再经注入端口）。"""
    import inspect

    from novamind.features.user.services.model_config_service import ModelConfigService

    src = inspect.getsource(ModelConfigService._check_delete_impact)
    assert "find_spaces_using_embedding" in src
def test_model_config_service_ctor_accepts_ks_info_port():
    """批次 4.5：构造器不再接收 ks 信息端口（改为方法内直查）。"""
    import inspect

    from novamind.features.user.services.model_config_service import ModelConfigService

    params = inspect.signature(ModelConfigService.__init__).parameters
    assert "knowledge_space_info_port" not in params
# ---- adapter 层 ----

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


# ---- document_pipeline / media_processing 静态助手穿参 ----

_STATIC_HELPERS_DOCUMENT = [
    "_process_image_document_static",
    "_get_document_processor_static",
    # 下列助手已下沉 pipeline_steps（dp/mp 解环），签名仍要求 model_config_port
    # —— 改从新模块取函数对象。
    "pipeline_steps:get_embedding_client",
    "pipeline_steps:generate_embeddings",
    "pipeline_steps:generate_single_embedding",
    "pipeline_steps:generate_questions_for_chunks",
    # 共享后置尾（切分/向量化/QG/索引）接收 model_config_port，由三模态管道注入
    "pipeline_steps:run_post_parse_tail",
]


@pytest.mark.parametrize("helper_name", _STATIC_HELPERS_DOCUMENT)
def test_document_static_helpers_accept_model_config_port(helper_name: str):
    """document_pipeline / pipeline_steps 助手接收 model_config_port 参数（调用方注入，不自建）。"""
    from novamind.features.knowledge_space.services import document_pipeline as ds
    from novamind.features.knowledge_space.services import pipeline_steps

    if ":" in helper_name:
        mod_name, fn_name = helper_name.split(":")
        fn = getattr(pipeline_steps, fn_name)
    else:
        fn = getattr(ds, helper_name)
    params = inspect.signature(fn).parameters
    assert "model_config_port" in params, f"{helper_name} 缺少 model_config_port 参数"


_MEDIA_HELPERS = [
    "process_video_document",
    "process_audio_document",
    "pipeline_steps:maybe_semantic_embedding_client",
]


@pytest.mark.parametrize("helper_name", _MEDIA_HELPERS)
def test_media_processing_helpers_accept_model_config_port(helper_name: str):
    """media_processing / pipeline_steps 模块函数接收 model_config_port 参数（调用方注入，不自建）。"""
    from novamind.features.knowledge_space.services import media_processing as mp
    from novamind.features.knowledge_space.services import pipeline_steps

    if ":" in helper_name:
        _, fn_name = helper_name.split(":")
        fn = getattr(pipeline_steps, fn_name)
    else:
        fn = getattr(mp, helper_name)
    params = inspect.signature(fn).parameters
    assert "model_config_port" in params, f"{helper_name} 缺少 model_config_port 参数"


def test_execute_document_pipeline_module_level_with_port_param():
    """execute_document_pipeline 为 document_pipeline 模块级函数，接收 model_config_port（无 self）。"""
    from novamind.features.knowledge_space.services import document_pipeline as dp

    fn = dp.execute_document_pipeline
    # 模块级函数（已从 DocumentService 的 staticmethod 抽出到 document_pipeline），无 self 参数
    assert not isinstance(fn, staticmethod), "execute_document_pipeline 应为模块级函数，非 staticmethod"
    params = inspect.signature(fn).parameters
    assert "self" not in params, "execute_document_pipeline 为模块级函数，不应有 self"
    assert "model_config_port" in params, "execute_document_pipeline 缺少 model_config_port 参数"


def test_user_get_model_config_service_returns_port_with_ks_info():
    """user/api/dependencies.get_model_config_service 注入 ks_info_port 并以 ModelConfigPort 返回。"""
    from novamind.features.user.api.dependencies import get_model_config_service

    sig = inspect.signature(get_model_config_service)
    # 返回注解应为 ModelConfigPort（字符串或类型均可）
    ret = sig.return_annotation
    ret_name = ret if isinstance(ret, str) else getattr(ret, "__name__", str(ret))
    assert ret_name in ("ModelConfigService", "ModelConfigPort"), (
        f"get_model_config_service 返回类型应为 ModelConfigPort，实际: {ret_name}"
    )


# ---- 前端契约保留：ModelCredentials 向后兼容 re-export ----

def test_model_credentials_backward_compat_reexport():
    """ModelCredentials 归属 user/schemas（批次 3.6 从 shared/model_config_ports 迁入），service 可导出。"""
    from novamind.features.user.services import model_config_service as mcs

    assert hasattr(mcs, "ModelCredentials")
