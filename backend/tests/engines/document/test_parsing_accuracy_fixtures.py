"""解析准确性夹具回归：复杂 xlsx / docx 的真实短板场景。

针对 2026-10 解析质量批次的三类准确性短板各建真实夹具：
- Excel：合并单元格（此前合并维度全空）、程序生成公式无缓存值（此前整表
  空串）、浮点/日期的 str() 噪音；
- DOCX：表格在文档中部（此前全部堆到文档尾）、标题层级（此前全部单个 #）、
  列表段（此前丢列表语义）、文本框（此前整体丢失）。
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from docx import Document as DocxDocument
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from openpyxl import Workbook, load_workbook

pytestmark = pytest.mark.unit


# ---------- Excel 夹具 ----------

def _build_complex_xlsx(path: Path) -> None:
    """三表工作簿：合并单元格 + 浮点/日期 + 程序生成公式 + 多级表头 + 嵌入图片。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "区域销售"
    ws["A1"] = "区域"
    ws["B1"] = "季度"
    ws["C1"] = "销售额（万元）"
    # 合并单元格：A2:A3 = 华东区（此前 A3 为空、行语义断裂）
    ws["A2"] = "华东区"
    ws.merge_cells("A2:A3")
    ws["B2"] = "Q1"
    ws["B3"] = "Q2"
    ws["C2"] = 1200.0
    ws["C3"] = 1350.5
    ws["A4"] = "华北区"
    ws["B4"] = datetime(2024, 6, 30)
    # 程序生成公式：无缓存值，data_only=True 视角为 None
    ws["C4"] = "=SUM(C2:C3)"
    # 多级表头 sheet：组头横向合并 + 次级子头（此前第 2 行表头被当数据行）
    ws2 = wb.create_sheet("分季度明细")
    ws2["A1"] = "区域"
    ws2["B1"] = "Q1"
    ws2.merge_cells("B1:C1")
    ws2["D1"] = "Q2"
    ws2.merge_cells("D1:E1")
    ws2["B2"] = "收入"
    ws2["C2"] = "成本"
    ws2["D2"] = "收入"
    ws2["E2"] = "成本"
    ws2["A3"] = "华东区"
    ws2["B3"] = 100
    ws2["C3"] = 60
    ws2["D3"] = 120
    ws2["E3"] = 70
    # 嵌入图片（此前完全丢失）
    from io import BytesIO

    from openpyxl.drawing.image import Image as XLImage
    from PIL import Image as PILImage

    buf = BytesIO()
    PILImage.new("RGB", (80, 60), color=(30, 144, 255)).save(buf, format="PNG")
    ws2.add_image(XLImage(buf), "B5")
    wb.save(path)


def test_excel_merged_cell_expanded_to_every_row(tmp_path):
    """合并单元格值展开：区域值出现在每一行，不再只有首行有值。"""
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    parser = RAGFlowExcelParser()
    lines = parser(xlsx.read_bytes())
    joined = "\n".join(lines)
    # 合并区第二行（Q2 行）此前区域列为空；展开后两行都带「华东区」
    assert joined.count("华东区") >= 2


def test_excel_value_formatting_cleans_noise(tmp_path):
    """浮点整数去 .0 尾、日期去零点时间——str() 默认形态是检索噪音。"""
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    parser = RAGFlowExcelParser()
    html_blocks = parser.html(xlsx.read_bytes())
    joined = "".join(html_blocks)
    assert "1200<" in joined or "1200<" in joined.replace(" ", ""), "浮点 1200.0 应显示为 1200"
    assert "00:00:00" not in joined, "零点时间尾巴应去除"
    assert "2024-06-30" in joined


def test_excel_formula_backfill_for_uncached_workbook(tmp_path):
    """程序生成公式（无缓存值）：公式字面量兜底，整表不再为空。"""
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    # sanity：data_only 视角 C4 确实为 None（openpyxl 写出的公式无缓存）
    wb = load_workbook(xlsx, data_only=True)
    assert wb["区域销售"]["C4"].value is None

    parser = RAGFlowExcelParser()
    lines = parser(xlsx.read_bytes())
    joined = "\n".join(lines)
    assert "=SUM(C2:C3)" in joined, "无缓存公式应以字面量兜底而非静默丢值"


def test_excel_multi_level_header_folded_to_composite(tmp_path):
    """多级表头：两级折成「Q1 > 收入」复合表头，表头行不再混进数据。"""
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    parser = RAGFlowExcelParser()
    blocks, _images = parser.parse_blocks(xlsx.read_bytes())
    detail = "".join(b for b in blocks if "分季度明细" in b)
    assert "<th>Q1 &gt; 收入</th>" in detail, "两级表头应折成复合表头"
    assert "<th>Q2 &gt; 成本</th>" in detail
    # 表头行不能混进数据行（此前「Q1：收入」成伪数据行）
    assert "<td>收入</td>" not in detail
    # 数据行完整
    assert "<td>华东区</td>" in detail and "<td>120</td>" in detail


def test_excel_embedded_image_extracted(tmp_path):
    """嵌入图片提取：png 化 blob + 锚点位置，随解析产物交付 figure 管线。"""
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    parser = RAGFlowExcelParser()
    blocks, images = parser.parse_blocks(xlsx.read_bytes())
    assert len(images) == 1
    image = images[0]
    assert image["sheet"] == "分季度明细"
    assert image["row"] == 4 and image["col"] == 1, "锚点 B5 → 0-based (row=4, col=1)"
    assert image["blob"][:8] == b"\x89PNG\r\n\x1a\n", "应重编码为 PNG"
    # 占位符挂本表首块
    detail = "".join(b for b in blocks if "分季度明细" in b)
    assert "__FIGURE_URL__xls_" in detail


def test_excel_runtime_figure_regions(tmp_path):
    """runtime 层组装 figure_regions（复用 PDF figure 上传管线）。"""
    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
        DeepDocParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    result = DeepDocParser()._parse_excel_sync(xlsx, "xlsx", {"chunk_size": 1000})
    regions = result.metadata["figure_regions"]
    assert len(regions) == 1
    assert regions[0]["image_blobs"] and regions[0]["artifact_id"].startswith("xls_")
    assert "分季度明细" in regions[0]["caption"]


# ---------- DOCX 夹具 ----------

def _build_complex_docx(path: Path) -> None:
    """标题两级 + 段落 + 中部表格 + 列表段 + 文本框的复杂文档。"""
    doc = DocxDocument()
    doc.add_heading("项目报告", level=1)
    doc.add_paragraph("项目背景说明段落。")
    doc.add_heading("财务数据", level=2)
    # 中部表格（此前被堆到文档尾）
    table = doc.add_table(rows=2, cols=3)
    for idx, value in enumerate(["科目", "预算", "实际"]):
        table.rows[0].cells[idx].text = value
    for idx, value in enumerate(["人力", "100", "90"]):
        table.rows[1].cells[idx].text = value
    doc.add_paragraph("表格之后的结论段落。")
    # 列表段（numPr）
    list_p = doc.add_paragraph("第一条行动项")
    p_pr = list_p._p.get_or_add_pPr()
    num_pr = parse_xml(
        f'<w:numPr {nsdecls("w")}><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
    )
    p_pr.append(num_pr)
    # 文本框（此前整体丢失）：txbxContent 直挂 body，解析器按 .//w:txbxContent 提取
    doc.element.body.append(parse_xml(
        f'<w:txbxContent {nsdecls("w")}>'
        f"<w:p><w:r><w:t>文本框内的流程标注ABC</w:t></w:r></w:p>"
        f"</w:txbxContent>"
    ))
    doc.save(path)


def test_docx_table_keeps_document_position(tmp_path):
    """表格在文档中部：产物 blocks 按文档序，表格不再堆到文档尾。"""
    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
        DeepDocParser,
    )

    docx = tmp_path / "complex.docx"
    _build_complex_docx(docx)
    result = DeepDocParser()._parse_docx_sync(docx, {"chunk_size": 1000})
    pos_report = result.full_text.find("项目报告")
    pos_table = result.full_text.find("科目")
    pos_conclusion = result.full_text.find("表格之后的结论段落")
    assert 0 <= pos_report < pos_table < pos_conclusion, (
        "表格应位于标题与后文之间（文档物理顺序），而非堆到文档尾"
    )


def test_docx_heading_level_reflected_in_marks(tmp_path):
    """标题层级映射到 # 数量（H1→#，H2→##），路径语境保留。"""
    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
        DeepDocParser,
    )

    docx = tmp_path / "complex.docx"
    _build_complex_docx(docx)
    result = DeepDocParser()._parse_docx_sync(docx, {"chunk_size": 1000})
    assert "## 项目报告 > 财务数据" in result.full_text


def test_docx_list_item_gets_bullet_prefix(tmp_path):
    """numPr 列表段带「• 」前缀，列表成员语义不再丢失。"""
    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
        DeepDocParser,
    )

    docx = tmp_path / "complex.docx"
    _build_complex_docx(docx)
    result = DeepDocParser()._parse_docx_sync(docx, {"chunk_size": 1000})
    assert "• 第一条行动项" in result.full_text


def test_docx_textbox_content_extracted(tmp_path):
    """文本框内容以 TextBox 段落保留（此前整体丢失）。"""
    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
        DeepDocParser,
    )

    docx = tmp_path / "complex.docx"
    _build_complex_docx(docx)
    result = DeepDocParser()._parse_docx_sync(docx, {"chunk_size": 1000})
    assert "文本框内的流程标注ABC" in result.full_text
