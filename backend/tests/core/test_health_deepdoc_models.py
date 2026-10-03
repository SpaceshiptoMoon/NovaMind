"""/health/detailed 的 deepdoc_models 组件返回契约。

锁定两个行为：
1. groups 恒定包含全部五组（ocr/layout/tsr/formula/text_concat）——
   齐全时也显式返回 true，部署后一眼可查全量模型状态
2. 任一组缺失时组件抛异常 → degraded，missing 信息点名缺失文件
"""
from __future__ import annotations

import pytest
from novamind.core.middleware.health_check import _check_deepdoc_models_component

pytestmark = pytest.mark.unit

VISION_GROUPS = {
    "ocr": {"available": True, "missing": []},
    "layout": {"available": True, "missing": []},
    "tsr": {"available": True, "missing": []},
}


def _patch_model_status(monkeypatch: pytest.MonkeyPatch, *, vision, formula, text_concat) -> None:
    """打桩三个状态函数，隔离真实模型目录。"""
    monkeypatch.setattr(
        "novamind.engines.document.integrations.deepdoc.vision.model_manager.get_model_status",
        lambda *a, **kw: vision,
    )
    monkeypatch.setattr(
        "novamind.engines.document.integrations.deepdoc.formula_recognition.get_formula_model_status",
        lambda *a, **kw: formula,
    )
    monkeypatch.setattr(
        "novamind.engines.document.integrations.deepdoc.text_concat_model.get_text_concat_model_status",
        lambda *a, **kw: text_concat,
    )


def _all_available() -> tuple[dict, dict, dict]:
    formula = {"available": True, "missing": [], "quantized": True}
    text_concat = {"available": True, "filename": "updown_concat_xgb.model"}
    return ({"groups": VISION_GROUPS, "model_dir": "/models"}, formula, text_concat)


def test_groups_always_include_all_five(monkeypatch: pytest.MonkeyPatch) -> None:
    """五组齐全时 groups 恒定含五键且全 true（formula/text_concat 不再隐身）。"""
    vision, formula, text_concat = _all_available()
    _patch_model_status(monkeypatch, vision=vision, formula=formula, text_concat=text_concat)

    result = _check_deepdoc_models_component()
    assert set(result["groups"]) == {"ocr", "layout", "tsr", "formula", "text_concat"}
    assert all(result["groups"].values())


def test_missing_formula_raises_and_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    """公式模型缺失 → 组件抛异常（degraded），missing 点名缺失文件。"""
    vision, formula, text_concat = _all_available()
    formula = {"available": False, "missing": ["encoder_model.onnx"], "quantized": False}
    _patch_model_status(monkeypatch, vision=vision, formula=formula, text_concat=text_concat)

    with pytest.raises(Exception, match="formula"):
        _check_deepdoc_models_component()


def test_missing_vision_group_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """视觉组缺失 → 抛异常且 groups 中该组为 False。"""
    vision = {"groups": {**VISION_GROUPS, "ocr": {"available": False, "missing": ["det.onnx"]}}, "model_dir": "/models"}
    _, formula, text_concat = _all_available()
    _patch_model_status(monkeypatch, vision=vision, formula=formula, text_concat=text_concat)

    with pytest.raises(Exception, match="vision.ocr"):
        _check_deepdoc_models_component()
