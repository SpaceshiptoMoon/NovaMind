"""Compatibility package for the new novamind import root.

历史背景：``backend/src/novamind/__init__.py`` 原本只是把 ``__path__`` 扩展到
``backend/src/``，使 ``novamind.core.* / novamind.features.* / novamind.shared.*`` 解析到
对应的 ``backend/src/<area>/`` 目录。

批次 6b 物理抽包后，``shared/`` 下的 ``ai_models/ storage/ prompts/`` 整目录、10 个端口
文件、以及 ``utils/`` 的 5 个叶（``ansi_strip/heartbeat/redact/time_utils/text_utils``）迁入
独立包 ``novamind-engine-core``（模块名 ``novamind_engine_core``）。宿主代码已全量改用
``from novamind_engine_core.<tail> import ...``，但为保过渡兼容（旧路径仍可用、双路径接缝测试、
第三方未迁移代码），本 shim 把每个迁出模块以 **同一模块对象** 挂到 ``novamind.shared.<tail>``
名下。

关键：**同一对象**别名（``sys.modules["novamind.shared.<tail>"] = <engine 模块>``），避免
同一文件以两个模块名加载导致类身份断裂（``isinstance`` / ``runtime_checkable`` Protocol /
ORM 枚举身份失效）。``novamind_engine_core`` 未安装时静默降级，不阻断宿主启动（但此时宿主
本身也无法 import 引擎模块，降级仅避免 shim 层报错）。

``novamind.shared`` 仍是命名空间包（无 ``__init__.py``），未迁出的
``novamind.shared.{cache,clients,mq,repository,knowledge,utils,utils.crypto}`` 继续在宿主
``backend/src/shared/`` 原地解析；迁出的 ``novamind.shared.<migrated>`` 走 sys.modules 别名
命中引擎包。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

_CURRENT_DIR = Path(__file__).resolve().parent
_SOURCE_ROOT = _CURRENT_DIR.parent

_source_root_str = str(_SOURCE_ROOT)
if _source_root_str not in __path__:
    __path__.append(_source_root_str)


# 迁出到 novamind-engine-core 的模块尾名（``novamind.shared.<tail>`` →
# ``novamind_engine_core.<tail>``）。须覆盖所有子包层级（包本身 + 叶），否则
# ``import novamind.shared.ai_models.base_model`` 这类多级导入会在中间包层落空。
# 不含 ``utils``（宿主包保留，留 crypto）与 ``utils.crypto``。
_ENGINE_CORE_TAILS = [
    # 10 个顶层端口/配置/异常/枚举文件
    "engine_ports",
    "engine_config",
    "engine_logging",
    "model_config_ports",
    "knowledge_space_info_ports",
    "search_ports",
    "registry_ports",
    "cache_ports",
    "rag_errors",
    "skill_ports",
    # ai_models 子树（包 + base_model + 三协议子包及其叶）
    "ai_models",
    "ai_models.base_model",
    "ai_models.llm",
    "ai_models.llm.openai_compatible",
    "ai_models.llm.anthropic_llm",
    "ai_models.llm.ollama_llm",
    "ai_models.llm.transformers_llm",
    "ai_models.embedding",
    "ai_models.embedding.openai_compatible",
    "ai_models.embedding.ollama_embedding",
    "ai_models.embedding.transformers_embedding",
    "ai_models.rerank",
    "ai_models.rerank.openai_rerank",
    "ai_models.rerank.transformers_rerank",
    # storage 子树
    "storage",
    "storage.elasticsearch_client",
    "storage.minio_client",
    "storage.index_schema",
    "storage.path_strategy",
    # prompts 子树
    "prompts",
    "prompts.prompt_manager",
    "prompts.templates",
    "prompts.sanitize",
    # utils 迁出叶（不含 utils 包本身与 crypto）
    "utils.ansi_strip",
    "utils.heartbeat",
    "utils.redact",
    "utils.time_utils",
    "utils.text_utils",
    "utils.text_utils.token_counter",
    "utils.text_utils.text_compressor",
]


def _install_engine_core_aliases() -> None:
    """把迁出模块以同一对象挂回 ``novamind.shared.<tail>`` 名下。

    不仅设置 ``sys.modules``（覆盖 ``import novamind.shared.<tail>`` 形态），
    还在父包上 ``setattr``（覆盖 ``from novamind.shared import <leaf>`` 形态）。
    """
    for tail in _ENGINE_CORE_TAILS:
        engine_name = f"novamind_engine_core.{tail}"
        host_name = f"novamind.shared.{tail}"
        try:
            module = importlib.import_module(engine_name)
        except ImportError:
            # novamind_engine_core 未安装或该子模块缺失：静默降级。
            # 宿主自身的 novamind_engine_core.* 直接导入会在更早处报错，此处不阻断。
            return
        sys.modules[host_name] = module
        # 在父包上挂属性，使 ``from novamind.shared.utils import heartbeat`` 这类
        # ``from package import submodule`` 形态经纯 getattr 命中（无需 importlib 兜底）。
        parent_tail, _, leaf = tail.rpartition(".")
        if parent_tail:
            parent_name = f"novamind.shared.{parent_tail}"
            parent = sys.modules.get(parent_name)
            if parent is not None:
                setattr(parent, leaf, module)


_install_engine_core_aliases()
