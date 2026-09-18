"""适配层 ↔ vendored 属性契约对齐测试。

适配层 `__init__` 有意不调 vendored `super().__init__()`（同步加载 OCR/xgb
模型 + 可能联网），自行落齐 vendored 的实例属性契约。本测试静态扫描 vendored
源码里所有 `self.<attr>` 赋值点，断言适配层 `__init__` 全部预置——vendored
未来加新实例状态时，这里第一时间报漂移，而不是在运行期 AttributeError。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

VENDORED_PDF_PARSER = (
    BACKEND_ROOT
    / "src"
    / "engines"
    / "document"
    / "integrations"
    / "deepdoc"
    / "vendor"
    / "ragflow"
    / "pdf_parser.py"
)


def _vendored_self_attributes() -> set[str]:
    tree = ast.parse(VENDORED_PDF_PARSER.read_text(encoding="utf-8"))
    attrs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "RAGFlowPdfParser":
            for item in node.body:
                if not isinstance(item, ast.FunctionDef):
                    continue
                for stmt in ast.walk(item):
                    targets = []
                    if isinstance(stmt, ast.Assign):
                        targets = stmt.targets
                    elif isinstance(stmt, ast.AnnAssign) and stmt.target is not None:
                        targets = [stmt.target]
                    elif isinstance(stmt, ast.AugAssign):
                        targets = [stmt.target]
                    for target in targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            attrs.add(target.attr)
    return attrs


@pytest.mark.unit
def test_adapter_init_covers_vendored_attribute_contract():
    """适配层 __init__ 必须预置 vendored 全部 self 属性（防继承后运行期漂移）。"""
    from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser

    parser = RAGFlowPdfParser()
    vendored_attrs = _vendored_self_attributes()
    assert vendored_attrs, "vendored 属性扫描不应为空——若为空说明扫描失效了"
    missing = sorted(attr for attr in vendored_attrs if not hasattr(parser, attr))
    assert missing == [], (
        f"vendored 实例属性未在适配层 __init__ 预置: {missing}；"
        "请在 RAGFlowPdfParser.__init__ 落齐（vendored 新增状态时同步此契约）"
    )


@pytest.mark.unit
def test_adapter_lazy_models_stay_unloaded():
    """构造适配层不得触发任何模型加载（ocr/layouter/tbl_det/updown_cnt_mdl 为 None）。"""
    from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser

    parser = RAGFlowPdfParser()
    assert parser.ocr is None
    assert parser.layouter is None
    assert parser.tbl_det is None
    assert parser.updown_cnt_mdl is None


@pytest.mark.unit
def test_inherited_vendored_merges_are_real():
    """删 stub 后继承到的必须是 vendored 真实现（函数模块可鉴别），而非 fork no-op。"""
    from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser
    from novamind.engines.document.integrations.deepdoc.vendor.ragflow import pdf_parser as vendored_mod

    for name in (
        "_text_merge",
        "_concat_downward",
        "_naive_vertical_merge",
        "_filter_forpages",
        "_merge_with_same_bullet",
        "_filter_forpages",
        "proj_match",
    ):
        func = getattr(RAGFlowPdfParser, name)
        assert func.__module__ == vendored_mod.__name__, (
            f"{name} 应继承 vendored 实现，实际定义于 {func.__module__}"
        )


@pytest.mark.unit
def test_vendored_domain_bridge_round_trip():
    """box→dict→box 桥在累积 Y 域往返后坐标与文本保持一致，position_tag 重算正确。"""
    from novamind.engines.document.integrations.deepdoc.parsers.pdf import (
        DeepDocPdfBox,
        RAGFlowPdfParser,
    )

    parser = RAGFlowPdfParser.__new__(RAGFlowPdfParser)
    # page_cum_height[p-1] = 第 p 页之前的累积高度（长度 = 页数 + 1）
    parser.page_cum_height = [0.0, 1e6, 2e6]

    boxes = [
        DeepDocPdfBox(page=1, x0=72.0, x1=300.0, top=100.0, bottom=112.0, text="page one"),
        DeepDocPdfBox(page=2, x0=80.0, x1=310.0, top=50.0, bottom=62.0, text="page two"),
    ]
    converted = parser._boxes_to_vendored_domain(boxes)
    assert converted[0]["page_number"] == 1
    assert converted[0]["top"] == 100.0  # page 1 偏移 0
    assert converted[1]["page_number"] == 2
    assert converted[1]["top"] == 50.0 + 1e6  # page 2 偏移生效

    restored = parser._boxes_from_vendored_domain(converted)
    assert [b.text for b in restored] == ["page one", "page two"]
    assert restored[1].top == 50.0  # 减回偏移回到 page-local
    assert restored[1].bottom == 62.0
    # 合并阶段 bbox 变更后 position_tag 必须重算为新坐标
    converted[1]["bottom"] += 20.0
    restored = parser._boxes_from_vendored_domain(converted)
    assert "@@2\t" in restored[1].position_tag
    assert "\t82.0##" in restored[1].position_tag
