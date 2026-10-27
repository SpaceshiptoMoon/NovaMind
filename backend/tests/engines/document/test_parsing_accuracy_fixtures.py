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
    # 多岛 sheet：前置标题行 + 空列分隔的左右两表 + 批注（此前整表搅在一起）
    from openpyxl.comments import Comment

    ws3 = wb.create_sheet("多岛统计")
    ws3["A1"] = "月度汇总（单位：件）"
    ws3["A2"] = "名称"
    ws3["B2"] = "数量"
    ws3["A3"] = "甲"
    ws3["B3"] = 10
    ws3["A4"] = "乙"
    ws3["B4"] = 20
    ws3["D2"] = "编码"
    ws3["E2"] = "单价"
    ws3["D3"] = "X1"
    ws3["E3"] = 9.5
    ws3["D4"] = "X2"
    ws3["E4"] = 8
    ws3["B3"].comment = Comment("含返修品", "张三")
    # 图表（此前完全丢失）：柱状图引用分季度明细数据
    from openpyxl.chart import BarChart, Reference

    chart = BarChart()
    chart.title = "华东区季度收支"
    chart.add_data(Reference(ws2, min_col=2, min_row=2, max_col=3, max_row=3),
                   titles_from_data=True)
    chart.set_categories(Reference(ws2, min_col=1, min_row=3, max_row=3))
    ws2.add_chart(chart, "G3")
    # 小计/小节/单位 sheet：聚合行打标 + outline 分组行 + 前置单位说明
    ws4 = wb.create_sheet("小计与分组")
    ws4["A1"] = "单位：件"
    ws4["A2"] = "名称"
    ws4["B2"] = "数量"
    ws4["A3"] = "甲"
    ws4["B3"] = 10
    ws4["A4"] = "乙"
    ws4["B4"] = 20
    ws4["A5"] = "小计"
    ws4["B5"] = 30
    ws4["A6"] = "华东分组"
    ws4.row_dimensions[6].outlineLevel = 1
    ws4["A7"] = "丙"
    ws4["B7"] = 5
    # 转置表：首行数值主导、维度在首列（行头在左）
    ws5 = wb.create_sheet("转置月度")
    ws5["A1"] = "指标"
    for col, value in ((2, 100), (3, 200), (4, 300), (5, 400)):
        ws5.cell(row=1, column=col, value=value)
    for row, label in ((2, "销售额"), (3, "成本"), (4, "利润")):
        ws5.cell(row=row, column=1, value=label)
        for col, value in ((2, 50), (3, 60), (4, 70), (5, 80)):
            ws5.cell(row=row, column=col, value=value + col)
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


def test_excel_three_level_and_uneven_header(tmp_path):
    """三级表头折成「年 > 半年 > 科目」；部分列缺级的复合表头正确降级。"""
    from io import BytesIO

    from openpyxl import Workbook
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "三级表头"
    ws["A1"] = "产品"; ws["B1"] = "2024年"; ws.merge_cells("B1:E1"); ws["F1"] = "备注"
    ws["A2"] = "产品"; ws["B2"] = "上半年"; ws.merge_cells("B2:C2")
    ws["D2"] = "下半年"; ws.merge_cells("D2:E2")
    ws["B3"] = "收入"; ws["C3"] = "成本"; ws["D3"] = "收入"; ws["E3"] = "成本"
    ws["A4"] = "A产品"; ws["B4"] = 100; ws["C4"] = 60
    ws["D4"] = 120; ws["E4"] = 70; ws["F4"] = "已审核"
    ws["A5"] = "B产品"; ws["B5"] = 80; ws["C5"] = 45; ws["D5"] = 90; ws["E5"] = 50
    buf = BytesIO()
    wb.save(buf)
    blocks, _images = RAGFlowExcelParser().parse_blocks(buf.getvalue())
    joined = "\n".join(blocks)
    # 三级复合表头
    assert "<th>2024年 &gt; 上半年 &gt; 收入</th>" in joined
    assert "<th>2024年 &gt; 下半年 &gt; 成本</th>" in joined
    # 不规则级数：备注列只有一级，复合后就是自身
    assert "<th>备注</th>" in joined
    # 表头行不混进数据
    assert "<td>上半年</td>" not in joined


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


def test_excel_multi_island_sheet_split(tmp_path):
    """一表多岛：空列分隔的左右两表切成独立表，前置标题行独立成文本块。"""
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    parser = RAGFlowExcelParser()
    blocks, _images = parser.parse_blocks(xlsx.read_bytes())
    joined = "\n".join(blocks)
    # 左右两表各自带表头（此前整表搅在一起）
    assert "<th>名称</th>" in joined and "<th>编码</th>" in joined
    assert "<td>甲</td>" in joined and "<td>X1</td>" in joined
    # 前置标题行独立成文本块（此前被第 1 行表头吞掉）
    assert "月度汇总（单位：件）" in joined
    # 两表的 caption 引用坐标应不同（左表 A 区，右表 D 区）
    assert "多岛统计!A" in joined and "多岛统计!D" in joined


def test_excel_cell_comment_inlined(tmp_path):
    """单元格批注内联进格文本（此前完全丢失）。"""
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    parser = RAGFlowExcelParser()
    blocks, _images = parser.parse_blocks(xlsx.read_bytes())
    joined = "\n".join(blocks)
    assert "[note(张三): 含返修品]" in joined


def test_excel_chart_rebuilt_as_data_table(tmp_path):
    """图表 XML：range 引用回读缓存值重建「类别+系列」数据表。"""
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    parser = RAGFlowExcelParser()
    blocks, _images = parser.parse_blocks(xlsx.read_bytes())
    chart_blocks = [b for b in blocks if "图表（bar）" in b]
    assert chart_blocks, "图表应重建为数据表"
    assert "华东区季度收支" in chart_blocks[0]
    assert "收入" in chart_blocks[0] and "<td>100</td>" in chart_blocks[0]
    assert "<td>60</td>" in chart_blocks[0]


def test_excel_subtotal_row_flagged(tmp_path):
    """小计行打标 `[小计] ` 前缀——聚合值与明细值可区分，不丢数据。"""
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    blocks, _images = RAGFlowExcelParser().parse_blocks(xlsx.read_bytes())
    joined = "\n".join(blocks)
    assert "[小计]" in joined
    assert "<td>30</td>" in joined, "小计数值保留不剔除"


def test_excel_section_row_split(tmp_path):
    """outline 分组行拆为 `[节] 标注`，表按小节断开续排。"""
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    blocks, _images = RAGFlowExcelParser().parse_blocks(xlsx.read_bytes())
    joined = "\n".join(blocks)
    assert "[节] 华东分组" in joined
    assert "小计与分组!" in joined
    # 表被小节行断开：同名 caption 出现 ≥2 次（续排）
    assert joined.count("<table><caption>小计与分组!") >= 2


def test_excel_unit_attached_to_caption(tmp_path):
    """前置「单位：件」挂到表格 caption（数值量纲可见）。"""
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    blocks, _images = RAGFlowExcelParser().parse_blocks(xlsx.read_bytes())
    joined = "\n".join(blocks)
    assert "（单位：件）" in joined


def test_excel_transpose_table_row_headers(tmp_path):
    """转置表：首列作行表头（th），caption 标注转置形态。"""
    from novamind.engines.document.integrations.deepdoc.parsers.excel import (
        RAGFlowExcelParser,
    )

    xlsx = tmp_path / "complex.xlsx"
    _build_complex_xlsx(xlsx)
    blocks, _images = RAGFlowExcelParser().parse_blocks(xlsx.read_bytes())
    transposed = [b for b in blocks if "转置月度" in b]
    assert transposed, "转置表应有产物"
    assert "转置表：行头在首列" in transposed[0]
    assert "<th>销售额</th>" in transposed[0]
    assert "<td>100</td>" in transposed[0]


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
    # 文本框：锚定在中部段落内（真实形态：textbox 挂在段落 drawing 中）
    mid = doc.add_paragraph()
    mid._p.append(parse_xml(
        f'<w:txbxContent {nsdecls("w")}>'
        f'<w:p><w:r><w:t>文本框内的流程标注ABC</w:t></w:r></w:p>'
        f"</w:txbxContent>"
    ))
    # 列表段（numPr）
    list_p = doc.add_paragraph("第一条行动项")
    p_pr = list_p._p.get_or_add_pPr()
    num_pr = parse_xml(
        f'<w:numPr {nsdecls("w")}><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
    )
    p_pr.append(num_pr)
    # 超链接段（此前 runs 累加丢 hyperlink 显示文本）
    link_p = doc.add_paragraph()
    link_p._p.append(parse_xml(
        f'<w:hyperlink {nsdecls("w")} r:id="rIdLink" '
        f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<w:r><w:t>点击访问文档门户</w:t></w:r></w:hyperlink>"
    ))
    # 内容控件包裹的段落与表格（此前整块跳过）
    doc.element.body.append(parse_xml(
        f'<w:sdt {nsdecls("w")}><w:sdtContent>'
        f'<w:p><w:r><w:t>附件说明条款</w:t></w:r></w:p>'
        f'<w:tbl><w:tr><w:tc><w:p><w:r><w:t>条款</w:t></w:r></w:p></w:tc>'
        f'<w:tc><w:p><w:r><w:t>内容</w:t></w:r></w:p></w:tc></w:tr>'
        f'<w:tr><w:tc><w:p><w:r><w:t>违约金</w:t></w:r></w:p></w:tc>'
        f'<w:tc><w:p><w:r><w:t>合同额两倍</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
        f"</w:sdtContent></w:sdt>"
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
    """文本框内容以 TextBox 段落保留，且原位锚定在所属段落之后。"""
    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
        DeepDocParser,
    )

    docx = tmp_path / "complex.docx"
    _build_complex_docx(docx)
    result = DeepDocParser()._parse_docx_sync(docx, {"chunk_size": 10000})
    assert "文本框内的流程标注ABC" in result.full_text
    pos_conclusion = result.full_text.find("表格之后的结论段落")
    pos_box = result.full_text.find("文本框内的流程标注ABC")
    pos_list = result.full_text.find("第一条行动项")
    assert 0 <= pos_conclusion < pos_box < pos_list, "文本框应锚定在其所属段落位置"


def test_docx_hyperlink_text_preserved(tmp_path):
    """超链接显示文本保全（runs 累加会丢 hyperlink 内文字）。"""
    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
        DeepDocParser,
    )

    docx = tmp_path / "complex.docx"
    _build_complex_docx(docx)
    result = DeepDocParser()._parse_docx_sync(docx, {"chunk_size": 10000})
    assert "点击访问文档门户" in result.full_text


def test_docx_sdt_content_passthrough(tmp_path):
    """内容控件（sdt）内的段落与表格穿透提取（此前整块跳过）。"""
    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
        DeepDocParser,
    )

    docx = tmp_path / "complex.docx"
    _build_complex_docx(docx)
    result = DeepDocParser()._parse_docx_sync(docx, {"chunk_size": 10000})
    assert "附件说明条款" in result.full_text
    assert "条款" in result.full_text and "内容" in result.full_text


def test_docx_tracked_changes_accepted_text(tmp_path):
    """修订模式按「接受终稿」提取：插入文本保留、删除文本丢弃。

    此前 w:ins/w:del 段落整段消失（python-docx runs/text 均不含修订内容）。
    """
    from io import BytesIO

    from docx import Document
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
        DeepDocParser,
    )

    doc = Document()
    doc.add_paragraph("修订前的普通段落。")
    p = doc.add_paragraph()
    p._p.append(parse_xml(
        f'<w:ins {nsdecls("w")} w:id="10" w:author="甲" '
        f'w:date="2026-01-01T00:00:00Z">'
        f"<w:r><w:t>插入的新条款文本</w:t></w:r></w:ins>"
    ))
    p2 = doc.add_paragraph()
    p2._p.append(parse_xml(
        f'<w:del {nsdecls("w")} w:id="11" w:author="甲" '
        f'w:date="2026-01-01T00:00:00Z">'
        f'<w:r><w:delText>被删除的旧条款文本</w:delText></w:r></w:del>'
    ))
    buf = BytesIO()
    doc.save(buf)
    result = DeepDocParser()._parse_docx_sync(buf.getvalue(), {"chunk_size": 10000})
    assert "插入的新条款文本" in result.full_text, "接受的插入文本必须保留"
    assert "被删除的旧条款文本" not in result.full_text, "拒绝的删除文本必须丢弃"


def test_docx_footnote_inlined(tmp_path):
    """脚注引用内联为 [脚注N: 文本]（此前完全丢失）。"""
    import io
    import zipfile

    from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
        DeepDocParser,
    )

    docx = tmp_path / "complex.docx"
    _build_complex_docx(docx)
    # zip 级注入 footnotes part + 关系 + 内容类型 + 段内引用（模拟真实脚注文档）
    src = docx.read_bytes()
    footnotes_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main">'
        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/>'
        "</w:r></w:p></w:footnote>"
        '<w:footnote w:id="2"><w:p><w:r><w:t>有效期自双方签字之日起算</w:t>'
        "</w:r></w:p></w:footnote></w:footnotes>"
    )
    rels_patch = (
        b'<Relationship Id="rIdFnX" Type="http://schemas.openxmlformats.org/'
        b'officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>'
    )
    ct_patch = (
        b'<Override PartName="/word/footnotes.xml" ContentType='
        b'"application/vnd.openxmlformats-officedocument.wordprocessingml.'
        b'footnotes+xml"/>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(src)) as zin, zipfile.ZipFile(
        buf, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item == "word/document.xml":
                text = data.decode("utf-8")
                marker = "项目背景说明段落。"
                idx = text.find(marker)
                assert idx >= 0
                insert_at = text.find("</w:p>", idx)
                ref = '<w:r><w:footnoteReference w:id="2"/></w:r>'
                text = text[:insert_at] + ref + text[insert_at:]
                data = text.encode("utf-8")
            elif item == "word/_rels/document.xml.rels":
                data = data.replace(b"</Relationships>", rels_patch + b"</Relationships>")
            elif item == "[Content_Types].xml":
                data = data.replace(b"</Types>", ct_patch + b"</Types>")
            zout.writestr(item, data)
        zout.writestr("word/footnotes.xml", footnotes_xml.encode("utf-8"))
    docx.write_bytes(buf.getvalue())

    result = DeepDocParser()._parse_docx_sync(docx, {"chunk_size": 10000})
    assert "[脚注2: 有效期自双方签字之日起算]" in result.full_text
    assert "项目背景说明段落。 [脚注2:" in result.full_text, "脚注应内联在所属段落"
