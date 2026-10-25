"""版面识别失败策略回归测试（发包模式：降级由调用方声明）。

``layout_failure_policy`` 两态：
- 默认 ``heuristic_fallback``：推理失败窗回退启发式布局，layout_source
  元数据可见（既有行为）；
- ``"raise"``：抛 ``LayoutInferenceError`` 由宿主决策（重试/失败/换路）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.integrations.deepdoc import LayoutInferenceError
from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser

pytestmark = pytest.mark.unit


def _parser_with_failing_layout(monkeypatch) -> RAGFlowPdfParser:
    """构造一个「layout 模型加载即失败」的解析器（模拟模型缺失/损坏）。"""
    parser = RAGFlowPdfParser.__new__(RAGFlowPdfParser)
    monkeypatch.setattr(
        parser, "_get_layout_recognizer",
        lambda: (_ for _ in ()).throw(RuntimeError("模型文件损坏")),
    )
    return parser


def test_exported_from_package():
    """LayoutInferenceError 从包门面导出（宿主 except 依赖）。"""
    assert issubclass(LayoutInferenceError, RuntimeError)
