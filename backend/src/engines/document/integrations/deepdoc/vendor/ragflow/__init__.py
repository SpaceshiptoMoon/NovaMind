"""RAGFlow DeepDoc 上游逐字 vendor 装载层。

`pdf_parser.py` 是 RAGFlow 仓库 `deepdoc/parser/pdf_parser.py` 的逐字拷贝
（Apache-2.0 头保留，仅文件头追加一行 vendor 来源注释），上游快照 commit
见 `novamind.engines.document.integrations.deepdoc.compat.upstream`。

上游文件在模块级 import `common.*` / `rag.*` / `deepdoc.vision` / `deepdoc.parser.utils`
（RAGFlow 仓库布局），本仓库没有这些顶层包。`install_stubs()` 以 sys.modules
预注册的方式提供最小 stub，使 vendored 文件**原样 import、原样运行**：

- stub 只做名字绑定与转发，属性尽量重导出真实本地实现
  （rag_tokenizer → compat.SimpleTokenizer、deepdoc.vision → 本地 vision 模块），
  即使被进程内其它代码拿到，行为也是正确的。
- 注册幂等：目标名已存在则跳过（不覆盖真实包）。
- 进程级副作用：`common` / `rag` / `deepdoc` 三个顶层名会被本模块占用。
  本仓库不依赖这些名字的真实包；若未来引入真正的同名包，应先 uninstall
  本 vendor 装载（删除 `vendor/ragflow/`）再迁移。

上游官方先例：RAGFlow 自家 DeepDoc Docker 镜像用同款 stub 生成器
（`deepdoc/server/docker_stubs.py`）解决同一 import 链问题。
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import types
from pathlib import Path

_STUB_MARKER = "__novamind_vendor_stub__"

# vendor 目录：backend/src/engines/document/integrations/deepdoc/vendor/ragflow/
_VENDOR_DIR = Path(__file__).resolve().parent
# <backend>/.cache/deepdoc —— model_manager 同款解析（DEEPDOC_MODEL_DIR 优先）
_MODEL_CACHE_DIR = (
    Path(os.getenv("DEEPDOC_MODEL_DIR"))
    if os.getenv("DEEPDOC_MODEL_DIR")
    else _VENDOR_DIR.parents[6] / ".cache" / "deepdoc"
)


def _register(name: str, module: types.ModuleType) -> None:
    """幂等注册：已存在且非本装载层的 stub 则不动（尊重真实包）。"""
    existing = sys.modules.get(name)
    if existing is not None and not getattr(existing, _STUB_MARKER, False):
        return
    setattr(module, _STUB_MARKER, True)
    sys.modules[name] = module


def _bootstrap_updown_model() -> None:
    """vendored `__init__` 期望 `<project_base>/rag/res/deepdoc/updown_concat_xgb.model`。

    stub 的 get_project_base_directory 返回 `.cache`，故把模型幂等 copy 到
    `.cache/rag/res/deepdoc/`（KB 级，跨平台无权限要求；vendored 自带的
    snapshot_download 是失败兜底，正常不会触达）。
    """
    target_dir = _MODEL_CACHE_DIR.parent / "rag" / "res" / "deepdoc"
    target = target_dir / "updown_concat_xgb.model"
    if target.exists() and target.stat().st_size > 0:
        return
    candidates = [
        _MODEL_CACHE_DIR / "updown_concat_xgb.model",
        _MODEL_CACHE_DIR / "text_concat" / "updown_concat_xgb.model",
    ]
    source = next((c for c in candidates if c.exists()), None)
    if source is None:
        return  # 无本地模型时交给 vendored 的 snapshot_download 兜底
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def install_stubs() -> None:
    """注册 vendored 代码依赖的全部顶层 stub。幂等，可重复调用。"""

    def _module(name: str, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        return mod

    # ── common.* ─────────────────────────────────────────────────────
    _register("common", _module("common"))

    from novamind.engines.document.integrations.deepdoc.compat.constants import (
        MAXIMUM_PAGE_NUMBER,
    )

    _register(
        "common.constants",
        _module("common.constants", MAXIMUM_PAGE_NUMBER=MAXIMUM_PAGE_NUMBER),
    )

    # 上游 `from common import settings` 拿到的是 common/settings.py 模块对象，
    # 因此 PARALLEL_DEVICES 必须是模块级属性（不是类属性）。
    # 上游由 torch.cuda.device_count() 填充；0/1 时多卡限流不启用，行为安全。
    _settings_mod = _module("common.settings", PARALLEL_DEVICES=int(os.getenv("PARALLEL_DEVICES", "0")))
    _register("common.settings", _settings_mod)

    def get_project_base_directory(*args):
        base = os.getenv("DEEPDOC_VENDOR_PROJECT_BASE") or str(_MODEL_CACHE_DIR.parent)
        if args:
            return os.path.join(base, *args)
        return base

    _register(
        "common.file_utils",
        _module("common.file_utils", get_project_base_directory=get_project_base_directory),
    )

    def thread_pool_exec(func, *args, **kwargs):
        # 仅 vendored 并行 OCR 路径使用（settings.PARALLEL_DEVICES > 1 才触达）；
        # 单卡环境直通调用。
        return func(*args, **kwargs)

    _register("common.misc_utils", _module("common.misc_utils", thread_pool_exec=thread_pool_exec))

    # ── rag.nlp / rag.prompts.generator ─────────────────────────────
    _register("rag", _module("rag"))

    from novamind.engines.document.integrations.deepdoc.compat.compat import rag_tokenizer

    _register("rag.nlp", _module("rag.nlp", rag_tokenizer=rag_tokenizer))

    def vision_llm_describe_prompt(*, page: int) -> str:
        # 仅 vendored VisionParser（VLM 整页描述）使用；主链不触达。
        return (
            f"Describe the content of PDF page {page}, "
            "preserving structure and key entities."
        )

    _register(
        "rag.prompts",
        _module("rag.prompts"),
    )
    _register(
        "rag.prompts.generator",
        _module("rag.prompts.generator", vision_llm_describe_prompt=vision_llm_describe_prompt),
    )

    # ── deepdoc.vision（重导出本地真实模块 + OCR 惰性别名）──────────
    _register("deepdoc", _module("deepdoc"))

    local_vision = importlib.import_module(
        "novamind.engines.document.integrations.deepdoc.vision"
    )

    class _LazyOCR(local_vision.OCR):
        """本地 OCR 默认 autoload=True（构造即加载 det/rec 模型），而 vendored
        `RAGFlowPdfParser.__init__` 会 `OCR()`。强制惰性：推理前 ensure_loaded 兜底
        （本地 OCR 的 detect/recognize 均已内置）。"""

        def __init__(self, *args, **kwargs):
            kwargs.setdefault("autoload", False)
            super().__init__(*args, **kwargs)

    # 直接把 vendored 期望的属性挂到本地 vision 模块的浅代理上，避免污染真实模块
    vision_proxy = _module(
        "deepdoc.vision",
        OCR=_LazyOCR,
        Recognizer=local_vision.Recognizer,
        LayoutRecognizer=getattr(local_vision, "LayoutRecognizer4YOLOv10"),
        AscendLayoutRecognizer=getattr(local_vision, "AscendLayoutRecognizer"),
        TableStructureRecognizer=local_vision.TableStructureRecognizer,
    )
    # 上游 `from deepdoc.vision import ...` 走属性；`from deepdoc.vision.operators import nms`
    # 等子模块 import 走 __path__ 透传到真实包
    vision_proxy.__path__ = list(local_vision.__path__)
    _register("deepdoc.vision", vision_proxy)

    # ── deepdoc.parser.utils（书签提取）────────────────────────────
    from novamind.engines.document.integrations.deepdoc.parsers.upstream.utils import (
        extract_pdf_outlines,
    )

    _register(
        "deepdoc.parser",
        _module("deepdoc.parser"),
    )
    _register(
        "deepdoc.parser.utils",
        _module("deepdoc.parser.utils", extract_pdf_outlines=extract_pdf_outlines),
    )

    _bootstrap_updown_model()


# import 本包即完成 stub 注册，保证 `from ...vendor.ragflow import pdf_parser`
# 任何入口都安全。
install_stubs()

from novamind.engines.document.integrations.deepdoc.vendor.ragflow import pdf_parser  # noqa: E402,F401

__all__ = ["pdf_parser", "install_stubs"]
