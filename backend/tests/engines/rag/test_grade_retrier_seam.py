"""GradeRetrier 引擎接缝测试。

守护 GradeRetrier 从 ``features/qa/services/`` 迁入 ``engines/rag/`` 后的接缝不变式：

  - ``engines/rag/grade_retrier.py`` 不得 import 宿主 ``features`` / ``setting`` /
    ``shared.prompts.PromptManager`` / ``core.middleware.structured_logging``（端口化后
    prompt 经注入的 ``PromptProvider``、日志经注入的 ``Logger``，切断引擎 -> 宿主导入边）。
  - ``GradeRetrier.__init__`` 必须接收 ``prompt_provider`` + ``logger`` 端口注入。
  - ``PromptManager`` 实例（批次 2.3 直用，结构化满足协议面）
    ``engines.ports.PromptProvider`` 协议。

断言方式：AST 扫描 import 模块名（精确，不受 docstring 文本干扰）+ 运行时协议检查。
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
SRC = BACKEND_ROOT / "src"

pytestmark = pytest.mark.unit


def _imports_in(path: Path) -> set[str]:
    """AST 收集文件内所有 import 的模块全名。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
    return mods


_GRADE_RETRIER = SRC / "engines" / "rag" / "grade_retrier.py"

_FORBIDDEN_PREFIXES = (
    "novamind.features",
    "novamind.setting",
    "novamind.shared.prompts",
    "novamind.core.middleware.structured_logging",
)


def test_grade_retrier_imports_acyclic():
    """批次 3 后：grade_retrier import 任意方向合法（R1），由无环门禁统一守护。"""
    import novamind.engines.rag.grade_retrier  # noqa: F401


def test_grade_retrier_ctor_requires_port_injection():
    """GradeRetrier.__init__ 必须接收 prompt_provider + logger 关键字注入。"""
    from novamind.engines.rag import GradeRetrier

    params = inspect.signature(GradeRetrier.__init__).parameters
    assert "prompt_provider" in params, "GradeRetrier.__init__ 缺少 prompt_provider 参数"
    assert "logger" in params, "GradeRetrier.__init__ 缺少 logger 参数"
    # 端口应为关键字必传（KEYWORD_ONLY）
    assert params["prompt_provider"].kind == inspect.Parameter.KEYWORD_ONLY
    assert params["logger"].kind == inspect.Parameter.KEYWORD_ONLY


def test_grade_retrier_exports_from_engines_rag():
    """GradeRetrier / GradeResult 从 engines.rag 公共面导出。"""
    from novamind.engines.rag import GradeResult, GradeRetrier

    assert GradeRetrier.__name__ == "GradeRetrier"
    assert GradeResult.__name__ == "GradeResult"


def test_qa_host_prompt_provider_satisfies_protocol():
    """qa 装配点直用的 PromptManager 满足 PromptProvider 消费面。"""
    from novamind.engines.ports import PromptProvider
    from novamind.shared.prompts.prompt_manager import PromptManager

    provider = PromptManager()
    assert isinstance(provider, PromptProvider)  # 结构化满足（duck-typed .get/.format）
    # 用真实注册的 qa_grade_retrieval 模板键验证 format 委托 PromptManager
    formatted = provider.format(
        "qa_grade_retrieval", query="测试查询", results="测试结果"
    )
    assert isinstance(formatted, str)
    assert len(formatted) > 0


def test_grade_retrier_uses_extract_json_obj_not_local_def():
    """GradeRetrier 复用 shared.utils.llm_response.extract_json_obj，无本地 _extract_json 定义。"""
    src = _GRADE_RETRIER.read_text(encoding="utf-8")
    assert "def _extract_json" not in src, "grade_retrier 不应再定义本地 _extract_json"
    assert "extract_json_obj" in src, "grade_retrier 应复用 extract_json_obj"