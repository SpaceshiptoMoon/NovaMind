"""批次4 StoragePort 接缝测试：ES/MinIO 通过注入 schema/strategy 工作，不 import setting/features。

验证 IndexSchema、PathStrategy 协议 + DefaultIndexSchema/MinioClient 通过注入
的宿主 adapters (NovamindIndexSchema/NovamindPathStrategy) 正确组装，且
``shared/storage/`` 下不 import ``novamind.setting`` 或 ``novamind.features``。
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

# ---- 受保护模块清单 ----
_ENGINE_STORAGE_MODULES = [
    "novamind_engine_core.storage.index_schema",
    "novamind_engine_core.storage.path_strategy",
    "novamind_engine_core.storage.elasticsearch_client",
    "novamind_engine_core.storage.minio_client",
    "novamind_engine_core.engine_config",
    "novamind.shared.knowledge.media_processing.audio.audio_utils",
]

_FORBIDDEN_PREFIXES = ("novamind.setting", "novamind.features")


def _imported_modules(mod):
    """从模块源码中提取所有导入的模块名（AST 解析，按行匹配文档字符串/注释）。"""
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


@pytest.mark.parametrize("mod_name", _ENGINE_STORAGE_MODULES)
def test_engine_storage_no_forbidden_imports(mod_name: str):
    """shared/storage/ 和 audio_utils 不得 import novamind.setting 或 novamind.features。"""
    mod = importlib.import_module(mod_name)
    imported = _imported_modules(mod)
    for imp in imported:
        assert not imp.startswith(_FORBIDDEN_PREFIXES), (
            f"{mod_name} 导入了禁止前缀: {imp}"
        )


def test_default_index_schema_is_runtime_checkable():
    """IndexSchema 协议应为 runtime_checkable，可在不导入实例的情况下用于 isinstance。"""
    from novamind_engine_core.storage.index_schema import IndexSchema, DefaultIndexSchema

    schema = DefaultIndexSchema()
    assert isinstance(schema, IndexSchema)
    assert schema.index_name(42) == "space_42"
    body = schema.build_create_body(768, "standard")
    assert "mappings" in body
    # 默认 dim 从参数中提取
    assert body["mappings"]["properties"]["embedding"]["dims"] == 768


def test_default_path_strategy_is_runtime_checkable():
    """PathStrategy 协议应为 runtime_checkable，并在独立使用时能正确工作。"""
    from novamind_engine_core.storage.path_strategy import PathStrategy, DefaultPathStrategy

    strategy = DefaultPathStrategy()
    assert isinstance(strategy, PathStrategy)
    assert "spaces/1/kbs/2/documents/3/myfile.pdf" in strategy.document_object_name(
        space_id=1, kb_id=2, document_id=3, storage_name="myfile.pdf"
    )
    assert strategy.document_prefix_for_kb(1, 2) == "spaces/1/kbs/2/"
    assert strategy.document_prefix_for_space(1) == "spaces/1/"
    assert strategy.avatar_object_name(42, "png").startswith("avatars/42/avatar")
    assert strategy.temp_object_name(session_id="sess123", filename="file.txt").startswith("temp/sess123/")


def test_novamind_adapters_inherit_defaults():
    """宿主 adapters 继承 engine 默认值（当前逐字一致）。"""
    from novamind_engine_core.storage.index_schema import DefaultIndexSchema
    from novamind_engine_core.storage.path_strategy import DefaultPathStrategy
    from novamind.features.knowledge_space.adapters.novamind_index_schema import (
        NovamindIndexSchema,
    )
    from novamind.features.knowledge_space.adapters.novamind_path_strategy import (
        NovamindPathStrategy,
    )

    assert isinstance(NovamindIndexSchema(), DefaultIndexSchema)
    assert isinstance(NovamindPathStrategy(), DefaultPathStrategy)


def test_audio_config_defaults():
    """AudioConfig 独立使用时应返回合理的默认值。"""
    from novamind_engine_core.engine_config import AudioConfig

    cfg = AudioConfig()
    assert cfg.local_whisper_model_dir is None


def test_audio_utils_resolve_accepts_audio_config():
    """_resolve_local_whisper_model_dir 接受 AudioConfig 并遵循优先级。"""
    from novamind_engine_core.engine_config import AudioConfig
    from novamind.shared.knowledge.media_processing.audio.audio_utils import (
        _resolve_local_whisper_model_dir,
    )

    # 不传 AudioConfig 时回退到环境变量 + 默认值
    result = _resolve_local_whisper_model_dir()
    assert isinstance(result, Path)

    # 传入 AudioConfig 时优先使用
    cfg = AudioConfig(local_whisper_model_dir="/fake/asr/model")
    result = _resolve_local_whisper_model_dir(cfg)
    assert result == Path("/fake/asr/model")