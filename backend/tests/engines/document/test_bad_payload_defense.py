"""坏文档防御回归：加密/伪格式/zip 炸弹/实体炸弹/CSV 编码/编码探测。

2026-10 坏文档防御批次的真实生产场景夹具（调研 python-docx/openpyxl/
POI/pypdf issue 得来的高频坏文档模式）：
- 加密 Office（OLE 头）与伪格式文件：显式 ParsePayloadError 族而非裸栈；
- zip 结构守卫：重复条目（内容静默不一致）与解压炸弹（内存放大）；
- XML 实体炸弹：OOXML part 内嵌 DTD 不展开；
- CSV 兜底：GBK/分隔符自动探测（Excel 中文系统另存场景）；
- 编码探测：gb18030 中文不被 utf-16 劫持（6d58ee1f 回归修复）；
- read_only 流式降级：超大 xlsx 放弃富特性换取可解析。
"""
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit

from novamind.engines.document.exceptions import (
    EncryptedDocumentError,
    MismatchedPayloadError,
)
from novamind.engines.document.integrations.deepdoc.compat import (
    decode_text_binary,
    find_codec,
    guard_office_zip,
    safe_fromstring,
)
from novamind.engines.document.integrations.deepdoc.parsers.docx import (
    RAGFlowDocxParser,
)
from novamind.engines.document.integrations.deepdoc.parsers.epub import (
    RAGFlowEpubParser,
)
from novamind.engines.document.integrations.deepdoc.parsers.excel import (
    RAGFlowExcelParser,
)
from novamind.engines.document.integrations.deepdoc.parsers.pdf import (
    RAGFlowPdfParser,
)
from novamind.engines.document.integrations.deepdoc.parsers.ppt import (
    RAGFlowPptParser,
)

_OLE_HEAD = b"\xd0\xcf\x11\xe0trash-but-ole-shaped-payload"


# ---------- 入口魔数守卫 ----------

def test_docx_ole_header_is_encrypted_error():
    """OLE 头假 docx → EncryptedDocumentError（加密容器或 .doc 改名）。"""
    with pytest.raises(EncryptedDocumentError):
        RAGFlowDocxParser()(_OLE_HEAD)


def test_docx_html_payload_is_mismatched_error():
    """HTML 伪 docx（CRM 导出改名场景）→ MismatchedPayloadError。"""
    with pytest.raises(MismatchedPayloadError):
        RAGFlowDocxParser()(b"<html><body><p>fake</p></body></html>")


def test_docx_corrupt_zip_is_mismatched_error():
    """PK 头但 zip 目录损坏 → MismatchedPayloadError（非 BadZipFile 裸栈）。"""
    with pytest.raises(MismatchedPayloadError):
        RAGFlowDocxParser()(b"PK\x03\x04not-a-real-zip-directory")


def test_xlsx_ole_header_is_encrypted_error():
    """OLE 头 xlsx（加密容器/旧版 .xls）→ EncryptedDocumentError。"""
    with pytest.raises(EncryptedDocumentError):
        RAGFlowExcelParser._load_excel_to_workbook(_OLE_HEAD)


def test_pptx_guards():
    """pptx OLE 头 → EncryptedDocumentError；HTML 伪格式 → Mismatched。"""
    with pytest.raises(EncryptedDocumentError):
        RAGFlowPptParser()(_OLE_HEAD)
    with pytest.raises(MismatchedPayloadError):
        RAGFlowPptParser()(b"<html>fake ppt</html>")


# ---------- zip 结构守卫 ----------

def test_zip_bomb_rejected():
    """高膨胀低压缩比条目（全 NUL 炸弹）→ MismatchedPayloadError。

    判据与 Apache POI ZipSecureFile 默认 minInflateRatio(0.01) 同款。
    """
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/worksheets/sheet1.xml", b"\x00" * (8 * 1024 * 1024))
    with pytest.raises(MismatchedPayloadError, match="解压炸弹"):
        guard_office_zip(buf.getvalue(), "xlsx")


def test_duplicate_zip_entry_rejected():
    """同名条目重复（拼接篡改，不同读取器选中不同条目）→ 拒收。"""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "a")
        zf.writestr("[Content_Types].xml", "b")
    with pytest.raises(MismatchedPayloadError, match="重复条目"):
        guard_office_zip(buf.getvalue(), "docx")


def test_legitimate_xlsx_passes_guard():
    """正常 xlsx（含高压缩文本 entry）不误伤。"""
    import tempfile
    from pathlib import Path

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in range(200):
        ws.append([f"项目{row}", row, "描述文字" * 5])
    path = Path(tempfile.mkdtemp()) / "ok.xlsx"
    wb.save(path)
    guard_office_zip(path.read_bytes(), "xlsx")  # 不抛即通过


# ---------- epub 容器守卫（上传门禁放开 epub 后补齐的最后一块防御） ----------

def _build_min_epub(extra_entries: dict[str, str] | None = None, *, with_container: bool = True) -> bytes:
    """构造最小合法 epub 字节流（正文/OPF 恒在，container/加密声明可变形）。"""
    buf = BytesIO()
    # DEFLATED：zip 炸弹判据依赖压缩比，STORED（默认）恒为 1 不触发
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        if with_container:
            zf.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                "</rootfiles></container>",
            )
        zf.writestr(
            "OEBPS/content.opf",
            '''<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0">
<manifest><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/></manifest>
<spine><itemref idref="c1"/></spine></package>''',
        )
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>章节正文段落。</p></body></html>")
        for name, content in (extra_entries or {}).items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_epub_not_zip_rejected():
    """HTML 伪 epub → MismatchedPayloadError（PK 魔数守卫）。"""
    with pytest.raises(MismatchedPayloadError):
        RAGFlowEpubParser()("memory.epub", binary=b"<html>fake epub</html>")


def test_epub_zip_bomb_rejected():
    """解压炸弹 epub → MismatchedPayloadError（guard_office_zip 对 OCF 容器同样生效）。"""
    payload = _build_min_epub({"OEBPS/bomb.bin": "\x00" * (8 * 1024 * 1024)})
    with pytest.raises(MismatchedPayloadError, match="解压炸弹"):
        RAGFlowEpubParser()("memory.epub", binary=payload)


def test_epub_duplicate_entries_rejected():
    """同名条目重复 epub → MismatchedPayloadError。"""
    payload = _build_min_epub({"OEBPS/ch1.xhtml": "duplicated-content"})
    with pytest.raises(MismatchedPayloadError, match="重复条目"):
        RAGFlowEpubParser()("memory.epub", binary=payload)


def test_epub_drm_encrypted_rejected():
    """encryption.xml 声明加密正文资源 → EncryptedDocumentError。"""
    drm_xml = (
        '<?xml version="1.0"?><encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
        'xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
        '<enc:EncryptedData><enc:CipherReference URI="OEBPS/ch1.xhtml"/></enc:EncryptedData>'
        "</encryption>"
    )
    payload = _build_min_epub({"META-INF/encryption.xml": drm_xml})
    with pytest.raises(EncryptedDocumentError):
        RAGFlowEpubParser()("memory.epub", binary=payload)


def test_epub_font_obfuscation_allowed():
    """仅字体混淆（加密对象全为字体文件）不误伤——文本层完好可解析。"""
    obf_xml = (
        '<?xml version="1.0"?><encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
        'xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
        '<enc:EncryptedData><enc:CipherReference URI="OEBPS/fonts/main.ttf"/></enc:EncryptedData>'
        "</encryption>"
    )
    payload = _build_min_epub({
        "META-INF/encryption.xml": obf_xml,
        "OEBPS/fonts/main.ttf": b"\x00\x01truetype-ish-bytes",
    })
    sections, figures = RAGFlowEpubParser()("memory.epub", binary=payload)
    assert any("章节正文段落" in s for s in sections)


def test_epub_corrupt_encryption_xml_rejected():
    """encryption.xml 存在但无法解析 → 按加密文档拒收（失败方向安全）。"""
    payload = _build_min_epub({"META-INF/encryption.xml": "not-xml-at-all"})
    with pytest.raises(EncryptedDocumentError):
        RAGFlowEpubParser()("memory.epub", binary=payload)


def test_epub_missing_container_xml_falls_back():
    """缺 container.xml：兜底文件名排序继续解析，不再解包崩溃（三元组回归）。"""
    payload = _build_min_epub(with_container=False)
    sections, figures = RAGFlowEpubParser()("memory.epub", binary=payload)
    assert any("章节正文段落" in s for s in sections)


# ---------- XML 实体炸弹 ----------

def test_dtd_entity_not_expanded():
    """内嵌 DTD 实体（billion laughs 放大器）不展开为内容。"""
    evil = (
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]><r>&b;</r>'
    )
    root = safe_fromstring(evil)
    # resolve_entities=False：实体引用保留为节点，不展开成 24 个 a
    assert "".join(root.itertext()).count("aaaa") == 0


# ---------- CSV 兜底：编码与分隔符 ----------

def test_csv_gbk_semicolon_detected():
    """GBK + 分号分隔 CSV（Excel 中文系统「CSV(分隔符)」另存）正确解析。"""
    payload = "名称;数量\n扳手;12\n锤子;7".encode("gb18030")
    wb = RAGFlowExcelParser._load_excel_to_workbook(payload)
    values = [
        str(cell.value)
        for ws in wb.worksheets
        for row in ws.iter_rows()
        for cell in row
        if cell.value
    ]
    joined = "|".join(values)
    assert "扳手" in joined and "12" in joined, f"GBK 分号 CSV 解析失败: {joined!r}"


def test_csv_utf16_tsv_detected():
    """UTF-16 TSV（Excel「Unicode 文本」导出）经消毒与分隔符探测解析。"""
    payload = "名称\t数量\n螺母\t30".encode("utf-16")
    wb = RAGFlowExcelParser._load_excel_to_workbook(payload)
    joined = "|".join(
        str(cell.value)
        for ws in wb.worksheets
        for row in ws.iter_rows()
        for cell in row
        if cell.value
    )
    assert "螺母" in joined and "30" in joined, f"UTF-16 TSV 解析失败: {joined!r}"


# ---------- 编码探测：gb18030 不被 utf-16 劫持（6d58ee1f 回归） ----------

def test_find_codec_gb18030_not_hijacked_by_utf16():
    """无 BOM gb18030 中文必须命中 gb18030（曾经被 utf-16 劫持成乱码）。"""
    assert find_codec("中文测试文档".encode("gb18030")) == "gb18030"
    assert find_codec("Report 报表 2024".encode("gb18030")) == "gb18030"
    assert decode_text_binary("中文测试文档".encode("gb18030")) == "中文测试文档"


def test_find_codec_utf16_scenarios_preserved():
    """UTF-16 识别不回归：BOM 直判；无 BOM 靠 NUL 特征（拉丁高字节）。"""
    assert find_codec("中文 Excel 导出".encode("utf-16")) == "utf-16"
    assert find_codec("plain english text".encode("utf-16-le")) == "utf-16"
    assert find_codec("中文 English mix".encode("utf-16-le")) == "utf-16"
    assert decode_text_binary("中文 Excel 导出".encode("utf-16")) == "中文 Excel 导出"


def test_find_codec_utf8_and_multibyte_others():
    """utf-8 正常命中；Shift-JIS 等 CJK 变体不再被 utf-16 劫持。"""
    assert find_codec("中文 UTF-8 文本".encode()) == "utf-8"
    # Shift-JIS 与 gb18030 码位重叠属统计歧义（可能静默乱码），但 utf-16
    # 劫持（更糟的确定性乱码）必须消除
    assert find_codec("日本語のテキスト".encode("shift-jis")) != "utf-16"


# ---------- read_only 流式降级 ----------

def test_excel_read_only_degradation_keeps_data():
    """超阈值 xlsx 切 read_only 流式解析：富特性降级但数据完整。"""
    import tempfile
    from pathlib import Path

    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    ws = wb.create_sheet()
    for row in range(60000):
        ws.append([f"项目编号{row}", row, row * 2, f"备注内容{row}", "描述文字" * 3])
    path = Path(tempfile.mkdtemp()) / "big.xlsx"
    wb.save(path)
    assert path.stat().st_size > 1024 * 1024, "夹具必须超过 1MB 阈值才走降级分支"

    blocks, images = RAGFlowExcelParser().parse_blocks(str(path), max_loaded_mb=1)
    big_text = "\n".join(blocks)
    assert "项目编号59999" in big_text, "降级路径数据不完整"


# ---------- PPT 图表与备注 ----------

def test_pptx_chart_and_notes_extracted():
    """原生图表系列数据与演讲者备注提取（此前整图静默丢失/备注不读）。"""
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    chart_data = CategoryChartData()
    chart_data.categories = ["Q1", "Q2"]
    chart_data.add_series("2024年", (120, 150))
    slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        Inches(1), Inches(1), Inches(4), Inches(3), chart_data,
    )
    slide.notes_slide.notes_text_frame.text = "本页讲解季度销量趋势"
    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp()) / "chart.pptx"
    prs.save(path)

    pages, ppt_figures = RAGFlowPptParser()(str(path))
    joined = "\n".join(pages)
    assert "2024年" in joined and "Q1=120" in joined, f"图表数据丢失: {joined!r}"
    assert "[备注] 本页讲解季度销量趋势" in joined, "演讲者备注丢失"
    assert ppt_figures == [], "无图片形状时 figures 应为空"


# ---------- PDF 加密 ----------

def _write_encrypted_pdf(path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "secret content")
    doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="secret")


def test_pdf_parser_encrypted_detected(tmp_path):
    """打开密码 PDF → EncryptedDocumentError（非底层 pdfminer 错误）。"""
    pdf = tmp_path / "enc.pdf"
    _write_encrypted_pdf(pdf)
    with pytest.raises(EncryptedDocumentError):
        RAGFlowPdfParser()(str(pdf), pdf_mode="plain")


def test_pdf_reader_encrypted_detected(tmp_path):
    """reader 层同样拦截加密 PDF（此前吞异常返回空列表）。"""
    from novamind.shared.document.readers.pdf_reader import PDFReader

    pdf = tmp_path / "enc.pdf"
    _write_encrypted_pdf(pdf)
    import asyncio

    with pytest.raises(EncryptedDocumentError):
        asyncio.run(PDFReader().load_data(str(pdf)))


# ---------- readers 层：坏文档显式上抛 ----------

def test_docx_reader_raises_on_fake_docx(tmp_path):
    """HTML 伪 docx 经 reader 上抛 MismatchedPayloadError（不再静默空列表）。"""
    from novamind.shared.document.readers.docx_reader import DocxReader

    fake = tmp_path / "fake.docx"
    fake.write_bytes(b"<html><body>not a docx</body></html>")
    import asyncio

    with pytest.raises(MismatchedPayloadError):
        asyncio.run(DocxReader().load_data(str(fake)))


def test_docx_reader_still_reads_normal_file(tmp_path):
    """正常 docx 不受守卫影响（防误伤回归）。"""
    from docx import Document as DocxDocument
    from novamind.shared.document.readers.docx_reader import DocxReader

    doc = DocxDocument()
    doc.add_paragraph("正常段落内容XYZ")
    path = tmp_path / "ok.docx"
    doc.save(path)
    import asyncio

    docs = asyncio.run(DocxReader().load_data(str(path)))
    assert docs and "正常段落内容XYZ" in docs[0]["text"]
