"""DeepDoc 金样对照基线测试（防线 2）。

历史教训：既有测试全是合成框单测（5 个手造 box 断言通过），而真实 PDF 一进来
就出现 22 个碎表/段落粘连——"代码与上游对齐"在测试体系上不可见。本文件用
程序生成的论文样式 PDF（标题/正文/网格表格/页码页脚）走完整 full 流水线，
把本轮修复的 6 个 bug 固化为**宏观行为基线**：

1. updown_concat 乱码修复    → 句号断段（"……结束。"与"第二章"不同段）
2. 页码框清理               → 输出无孤立页码行
3. layout drop=True         → 逐页重复的页眉不进正文（观察性，模型边界行为不锁）
4. 扫描页 zoom 自适应 2→3    → 无文字层页走纯 OCR 路径（vendored-ocr strategy）
5. 表格 layoutno 区域分组    → 表格结构被 TSR 检出（行列 ≥2）、表题挂 caption
6. xgboost 合并模型可用       → 模型在时 merge 策略必须为 xgboost（静默回退不可再犯）

断言刻意只锁"宏观指标"（结构行为），不锁单元格文本/页眉剔除等依赖模型
精度边界的输出——那些由单测覆盖。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

pytest.importorskip("fitz")

from novamind.engines.document.integrations.deepdoc.text_concat_model import get_text_concat_model_status
from novamind.engines.document.integrations.deepdoc.vision_runtime import get_vision_runtime_status
from novamind.engines.document.integrations.deepdoc.parsers.pdf import RAGFlowPdfParser

TITLE_P1 = "第一章数据处理方法"
TITLE_P2 = "第二章实验结果"
TABLE_CAPTION = "表1: 算法性能比较"


def _make_text_pdf(path: Path) -> None:
    """论文样式 fixture：页眉 + 编号标题 + 正文（句号断段样例）+ 网格表格 + 页码。"""
    import fitz

    doc = fitz.open()
    font = "china-s"
    for page_no in (1, 2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((250, 30), f"金样文档第{page_no}页", fontname=font, fontsize=9)
        y = 90
        if page_no == 1:
            page.insert_text((180, y), TITLE_P1, fontname=font, fontsize=16)
            y += 34
            page.insert_text((60, y), "本段先讲背景与现状，说明数据处理的动因。", fontname=font, fontsize=12)
            y += 24
            page.insert_text((60, y), "这句话结束了。", fontname=font, fontsize=12)
            y += 24
            page.insert_text((180, y), TITLE_P2, fontname=font, fontsize=16)
            y += 34
            tx, ty = 60, y
            col_w, row_h = 150, 26
            rows = [["算法", "迭代次数", "误差"], ["CG", "53", "8.10e-09"], ["AG", "81", "7.75e-09"]]
            page.insert_text((tx + 60, ty - 6), TABLE_CAPTION, fontname=font, fontsize=11)
            for r in range(4):
                page.draw_line(fitz.Point(tx, ty + r * row_h), fitz.Point(tx + 3 * col_w, ty + r * row_h), width=0.8)
            for c in range(4):
                page.draw_line(fitz.Point(tx + c * col_w, ty), fitz.Point(tx + c * col_w, ty + 3 * row_h), width=0.8)
            for ri, row in enumerate(rows):
                for ci, cell in enumerate(row):
                    page.insert_text((tx + ci * col_w + 12, ty + (ri + 1) * row_h - 8), cell, fontname=font, fontsize=11)
            y = ty + 3 * row_h + 30
            page.insert_text((60, y), "表格之后的正文段落继续。", fontname=font, fontsize=12)
        else:
            page.insert_text((60, y), "第二页正文段落，用于跨页段落合并。", fontname=font, fontsize=12)
        page.insert_text((285, 810), str(page_no), fontname=font, fontsize=11)
    doc.save(str(path))
    doc.close()


def _make_scanned_pdf(text_pdf: Path, path: Path) -> None:
    """把文字版逐页光栅化成整页位图，得到无文字层的扫描版。"""
    import fitz

    src = fitz.open(str(text_pdf))
    doc = fitz.open()
    for page in src:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        img_doc = fitz.open(stream=pix.tobytes("png"), filetype="png")
        pdf_bytes = img_doc.convert_to_pdf()
        img_doc.close()
        img_pdf = fitz.open("pdf", pdf_bytes)
        doc.insert_pdf(img_pdf)
        img_pdf.close()
    doc.save(str(path))
    doc.close()
    src.close()


@pytest.fixture(scope="module")
def golden_pdfs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("deepdoc_golden")
    text_pdf = tmp / "golden_text.pdf"
    scanned_pdf = tmp / "golden_scanned.pdf"
    _make_text_pdf(text_pdf)
    _make_scanned_pdf(text_pdf, scanned_pdf)
    return text_pdf, scanned_pdf


def _vision_available() -> bool:
    return bool(get_vision_runtime_status()["available"])


def _parse(pdf_path: Path) -> tuple[str, dict]:
    logging.disable(logging.CRITICAL)
    try:
        parser = RAGFlowPdfParser()
        result = parser(str(pdf_path), pdf_mode="full", chunk_size=1000)
    finally:
        logging.disable(logging.NOTSET)
    return result.full_text, result.metadata


def _maybe_snapshot(name: str, full_text: str, meta: dict) -> None:
    """金样快照钩子：env DEEPDOC_GOLDEN_SNAPSHOT_DIR 时落盘 full_text + 关键 metadata。

    用于重构前后 diff：设同一目录跑重构前/后各一次，对比 *_full_text.txt 即可
    核对段落边界/顺序/清理行为变化。
    """
    out_dir = os.environ.get("DEEPDOC_GOLDEN_SNAPSHOT_DIR")
    if not out_dir:
        return
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}_full_text.txt").write_text(full_text, encoding="utf-8")
    keys = (
        "vision_strategy",
        "ocr_sources",
        "paragraph_merge_strategy",
        "table_regions",
        "figure_regions",
        "page_count",
    )
    payload = {k: meta.get(k) for k in keys if k in meta}
    (out / f"{name}_meta.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def _no_standalone_page_number_lines(full_text: str) -> bool:
    """输出中不得出现孤立页码行（页码框清理的宏观断言）。"""
    for line in full_text.split("\n"):
        if line.strip() in {"1", "2", "- 1 -", "- 2 -"}:
            return False
    return True


@pytest.mark.slow
def test_golden_text_pdf_baseline(golden_pdfs):
    """文字版金样：文字层融合路径 + 断段 + 页码清理 + 表格结构 + 模型策略。"""
    if not _vision_available():
        pytest.skip("DeepDoc vision runtime unavailable")
    text_pdf, _ = golden_pdfs
    full_text, meta = _parse(text_pdf)
    _maybe_snapshot("golden_text", full_text, meta)

    # 文字版必须走文字层融合（误判成 OCR 说明乱码检测过激）
    assert meta["vision_strategy"] == "text-layer+onnx-layout", meta["vision_strategy"]
    # 标题保留（文字层提取正确性）
    assert TITLE_P1 in full_text.replace(" ", ""), "第一章标题应出现在输出中"
    assert TITLE_P2 in full_text.replace(" ", ""), "第二章标题应出现在输出中"
    # 乱码修复回归：句号段与下一标题必须断开（修复前粘连成一行）。
    # 只删空格、保留换行——若粘连，两者会出现在同一行。
    single_line = full_text.replace(" ", "")
    assert "这句话结束了。第二章" not in single_line, "句号后应断段，不得与下一标题粘连"
    # 页码框清理
    assert _no_standalone_page_number_lines(full_text), "输出不得残留孤立页码行"
    # 表格结构检出 + 表题挂载（layoutno 区域分组 + TSR）
    tables = meta["table_regions"]
    assert tables, "网格表格应被检出"
    structured = [t for t in tables if t["row_count"] >= 2 or t["column_count"] >= 2]
    assert structured, f"表格结构识别失败: {[(t['row_count'], t['column_count']) for t in tables]}"
    assert any("表1" in (t["caption"] or "") for t in tables), f"表题应挂载到 caption: {[t['caption'] for t in tables]}"
    # xgboost 段落合并模型可用时必须真正启用（静默回退不可再犯）
    if get_text_concat_model_status()["available"]:
        assert meta["paragraph_merge_strategy"] == "xgboost", (
            f"模型文件在但策略为 {meta['paragraph_merge_strategy']}——回退必须可见且不可接受"
        )


@pytest.mark.slow
def test_golden_scanned_pdf_baseline(golden_pdfs):
    """扫描版金样：无文字层页走纯 OCR 路径（zoom≥3 分支）+ OCR 中文基本质量。"""
    if not _vision_available():
        pytest.skip("DeepDoc vision runtime unavailable")
    _, scanned_pdf = golden_pdfs
    full_text, meta = _parse(scanned_pdf)
    _maybe_snapshot("golden_scanned", full_text, meta)

    # 扫描页无文字层 → 必须走 vendored OCR（zoom 自适应 3 起检的间接证据）
    assert meta["vision_strategy"] == "vendored-ocr+onnx-layout", meta["vision_strategy"]
    assert all(source == "vendored_ocr" for source in meta["ocr_sources"]), meta["ocr_sources"]
    # OCR 中文基本识别质量：标题主体字符应被识别（fitz 内置字体渲染的规整中文）
    assert "第一章" in full_text.replace(" ", ""), "OCR 应识别出第一章标题主体"
    # 页码框清理在 OCR 路径同样生效
    assert _no_standalone_page_number_lines(full_text), "OCR 路径同样不得残留孤立页码行"