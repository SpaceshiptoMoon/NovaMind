"""combined 策略（OCR + VLM caption 合并）与幻觉交叉校验回归（2026-10 批次3）。

门禁：
1. schema 第三档 combined 存在；
2. 合并语义：双通道成功 = caption + 去重后的 OCR 补充；单通道成功直接用
   （失败方向安全）；双失败空串交由调用方抛错；
3. 重叠去重：caption【图中文字】已基本覆盖 OCR 内容时不并【OCR 补充】段
   （防同内容双份入库稀释 embedding）；
4. 幻觉校验 warning-only：信号进任务 metrics，不改写入库文本；OCR 为空时
   无反证基准不产信号（宁漏报不误报）。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    ImageParsingConfig,
    build_runtime_parsing_config,
)
from novamind.features.knowledge_space.services import document_pipeline

pytestmark = pytest.mark.unit

_SILENT_LOGGER = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)


# ---------------------------------------------------------------------------
# 1. schema
# ---------------------------------------------------------------------------


def test_combined_strategy_in_schema():
    cfg = ImageParsingConfig.model_validate({"strategy": "combined", "vlm_model": "m"})
    assert cfg.strategy == "combined"
    with pytest.raises(Exception):
        ImageParsingConfig.model_validate({"strategy": "hybrid"})


def test_combined_vlm_description_enabled_flat_key():
    """combined 也走 VLM 描述，扁平 vlm_description_enabled 应置 True。"""
    runtime = build_runtime_parsing_config(
        {"image": {"strategy": "combined", "vlm_model": "m"}}, file_type="png"
    )
    assert runtime["image_strategy"] == "combined"
    assert runtime["vlm_description_enabled"] is True


# ---------------------------------------------------------------------------
# 2. 重叠去重判定（_text_subsumed）
# ---------------------------------------------------------------------------


def test_text_subsumed_when_caption_covers_ocr():
    """caption 已逐字转录 OCR 内容 → 判定覆盖，不并【OCR 补充】。"""
    ocr = "NovaMind X100 智能知识库平台 用户手册 v2.1"
    caption_portion = "标题「NovaMind X100 智能知识库平台」，副标题「用户手册 v2.1」"
    assert document_pipeline._text_subsumed(caption_portion, ocr) is True


def test_text_subsumed_false_when_ocr_has_exclusive_content():
    """OCR 有 caption 未覆盖的内容（表格数字等）→ 不覆盖，应并入补充段。"""
    ocr = "季度营收 1,284 万元 同比增长 23.6% 毛利率 41.2%"
    caption_portion = "一张财务报表，含多个数据列"
    assert document_pipeline._text_subsumed(caption_portion, ocr) is False


def test_text_subsumed_empty_ocr_counts_as_covered():
    """OCR 空（图片无文字/OCR 漏检）→ 无可补充，视为覆盖。"""
    assert document_pipeline._text_subsumed("任意 caption", "") is True
    assert document_pipeline._text_subsumed("任意 caption", "   ") is True


# ---------------------------------------------------------------------------
# 3. 幻觉交叉校验（_check_caption_hallucination，warning-only）
# ---------------------------------------------------------------------------


def test_hallucination_signal_when_entities_missing_from_ocr():
    """caption 声称的实体在非空 OCR 全文中完全无踪 → 产信号。"""
    caption = (
        "【主体描述】一张产品图\n"
        "【图中文字】完全无关的内容\n"
        "【图表数据】无\n"
        "【实体】量子跃迁引擎、星舰九号、曲率驱动\n"
        "【视觉特征】深色调\n"
        "【场景类型】照片"
    )
    ocr = " NovaMind X100 User Manual "
    signals = document_pipeline._check_caption_hallucination(caption, ocr)
    assert signals, "实体全部无踪应产幻觉信号"
    assert "量子跃迁引擎" in signals[0]


def test_no_signal_when_entities_present_in_ocr():
    """实体在 OCR 全文中有踪 → 无信号。"""
    caption = (
        "【主体描述】一张产品图\n"
        "【图中文字】产品名\n"
        "【图表数据】无\n"
        "【实体】NovaMind、X100\n"
        "【视觉特征】深色调\n"
        "【场景类型】照片"
    )
    ocr = "NovaMind X100 智能知识库平台"
    assert document_pipeline._check_caption_hallucination(caption, ocr) == []


def test_no_signal_when_ocr_empty_or_entities_none():
    """OCR 为空（无反证基准）或实体段为「无」→ 不产信号（宁漏报不误报）。"""
    caption_with = (
        "【主体描述】x\n【图中文字】y\n【图表数据】无\n【实体】不存在的实体甲\n"
        "【视觉特征】z\n【场景类型】照片"
    )
    caption_none = (
        "【主体描述】x\n【图中文字】无\n【图表数据】无\n【实体】无\n"
        "【视觉特征】z\n【场景类型】照片"
    )
    assert document_pipeline._check_caption_hallucination(caption_with, "") == []
    assert document_pipeline._check_caption_hallucination(caption_none, "一些 OCR 文字") == []


# ---------------------------------------------------------------------------
# 4. 合并端到端（_process_image_combined_static）
# ---------------------------------------------------------------------------


def _make_document() -> SimpleNamespace:
    return SimpleNamespace(
        id=81,
        space_id=1,
        kb_id=1,
        file_hash="h",
        file_type="png",
        filename="a.png",
        storage={"minio_object_name": "obj"},
        uploader_id=1,
    )


def _patch_inner_calls(monkeypatch, *, ocr_text: str | Exception, caption: str | Exception):
    """patch combined 依赖的两个内部函数（OCR 与 caption 生成）。"""

    async def _ocr(document, file_content, session, _logger):
        if isinstance(ocr_text, Exception):
            raise ocr_text
        return ocr_text

    async def _caption(file_content, document, mcs, _logger, vlm_model_name=None,
                       vlm_fallback_model=None):
        if isinstance(caption, Exception):
            raise caption
        return caption

    monkeypatch.setattr(document_pipeline, "_process_image_ocr_static", _ocr)
    monkeypatch.setattr(document_pipeline, "_generate_image_description", _caption)


@pytest.mark.asyncio
async def test_combined_merges_caption_and_exclusive_ocr(monkeypatch):
    """双通道成功 + OCR 有 caption 未覆盖内容 → caption +【OCR 补充】合并。"""
    caption = (
        "【主体描述】一张财务报表\n"
        "【图中文字】无\n"
        "【图表数据】营收相关数据\n"
        "【实体】季度报表\n"
        "【视觉特征】表格布局\n"
        "【场景类型】图表"
    )
    ocr = "季度营收 1284 万元 同比增长 23.6%"
    _patch_inner_calls(monkeypatch, ocr_text=ocr, caption=caption)

    result = await document_pipeline._process_image_combined_static(
        document=_make_document(),
        file_content=b"\x89PNG",
        session=None,
        _logger=_SILENT_LOGGER,
        model_config_port=None,
        vlm_model_name="m",
        task=None,
    )
    assert "【主体描述】" in result and "一张财务报表" in result
    assert "【OCR 补充】" in result and "1284" in result


@pytest.mark.asyncio
async def test_combined_skips_ocr_section_when_covered(monkeypatch):
    """caption 已覆盖 OCR 内容 → 不并【OCR 补充】（防同内容双份）。"""
    caption = (
        "【主体描述】一张产品命名图\n"
        "【图中文字】NovaMind X100 智能知识库平台 用户手册 v2.1\n"
        "【图表数据】无\n"
        "【实体】NovaMind、X100\n"
        "【视觉特征】白底黑字\n"
        "【场景类型】截图"
    )
    ocr = "NovaMind X100 智能知识库平台 用户手册 v2.1"
    _patch_inner_calls(monkeypatch, ocr_text=ocr, caption=caption)

    result = await document_pipeline._process_image_combined_static(
        document=_make_document(),
        file_content=b"\x89PNG",
        session=None,
        _logger=_SILENT_LOGGER,
        model_config_port=None,
        vlm_model_name="m",
        task=None,
    )
    assert "【OCR 补充】" not in result, "caption 已覆盖 OCR 时不应并重复补充段"
    assert "NovaMind X100" in result


@pytest.mark.asyncio
async def test_combined_degrades_to_pure_ocr_on_vlm_failure(monkeypatch):
    """VLM 失败 → 降级纯 OCR（失败方向安全：能力缺失而非错误结果）。"""
    _patch_inner_calls(
        monkeypatch,
        ocr_text="纯 OCR 提取的文字",
        caption=RuntimeError("401 unauthorized"),
    )

    result = await document_pipeline._process_image_combined_static(
        document=_make_document(),
        file_content=b"\x89PNG",
        session=None,
        _logger=_SILENT_LOGGER,
        model_config_port=None,
        vlm_model_name="m",
        task=None,
    )
    assert result == "纯 OCR 提取的文字"


@pytest.mark.asyncio
async def test_combined_degrades_to_pure_caption_on_ocr_failure(monkeypatch):
    """OCR 失败（如 cv2 缺失）→ 降级纯 caption，不阻塞。"""
    _patch_inner_calls(
        monkeypatch,
        ocr_text=RuntimeError("No module named 'cv2'"),
        caption="【主体描述】纯 caption\n【图中文字】无\n【图表数据】无\n【实体】无\n【视觉特征】x\n【场景类型】照片",
    )

    result = await document_pipeline._process_image_combined_static(
        document=_make_document(),
        file_content=b"\x89PNG",
        session=None,
        _logger=_SILENT_LOGGER,
        model_config_port=None,
        vlm_model_name="m",
        task=None,
    )
    assert "【主体描述】纯 caption" in result


@pytest.mark.asyncio
async def test_combined_both_fail_returns_empty(monkeypatch):
    """双双失败 → 空串（调用方抛错），不产半成品。"""
    _patch_inner_calls(
        monkeypatch,
        ocr_text=RuntimeError("ocr boom"),
        caption=RuntimeError("vlm boom"),
    )

    result = await document_pipeline._process_image_combined_static(
        document=_make_document(),
        file_content=b"\x89PNG",
        session=None,
        _logger=_SILENT_LOGGER,
        model_config_port=None,
        vlm_model_name="m",
        task=None,
    )
    assert result == ""
