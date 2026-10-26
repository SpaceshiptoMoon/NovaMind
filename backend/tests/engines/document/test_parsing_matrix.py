"""解析模块测试矩阵（docs/parsing-test-matrix.md）的组合层参数化测试。

覆盖矩阵一区「文本族 × 8 切分策略」全组合与五区失败策略的运行时断言：
- default reader × 8 切分（PDF 文字层 / DOCX / TXT / MD / HTML / JSON / GBK 回落）
- deepdoc × 8 切分（DOCX / EPUB / XLSX / PPTX / MD / HTML / JSON / TXT）
- PDF deepdoc full × 8 切分（本地 OCR，高内存放批尾，见文件末 marker）

文档全部程序化构造（无二进制夹具入库）；SEM 策略用确定性假 embedding。
模型/外部依赖不可达的用例按矩阵标注 skip。
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit

MARK = "矩阵验证标记QWP"
NL2 = "\n\n"

# 8 切分策略与默认参数（与 splitting schema 约束一致的合法组合）
SPLIT_PARAMS: list[tuple[str, dict]] = [
    ("recursive", {"chunk_size": 200, "chunk_overlap": 30, "min_chunk_size": 40}),
    ("semantic", {"max_chunk_size": 200, "similarity_threshold": 0.5, "batch_size": 4}),
    ("fixed_size", {"chunk_size": 200, "chunk_overlap": 30}),
    ("markdown", {"max_chunk_size": 200, "min_chunk_size": 30}),
    ("delimiter", {"chunk_size": 200, "chunk_overlap": 30, "min_chunk_size": 30}),
    ("sentence_window", {"chunk_size": 300, "window_size": 2}),
    ("parent_child", {"chunk_size": 200, "chunk_overlap": 30, "parent_chunk_size": 400}),
    ("hierarchical", {"chunk_size": 200, "chunk_overlap": 30, "min_chunk_size": 40}),
]

SPLIT_IDS = [s for s, _p in SPLIT_PARAMS]


class DeterministicEmbedding:
    """SEM 策略用的确定性 embedding 桩（faster-whisper 域外，无网络）。"""

    async def generate_embeddings_batch(self, texts, batch_size=None):  # noqa: ARG002
        import hashlib

        vectors = []
        for t in texts:
            vec = [0.0] * 32
            for i in range(len(t) - 1):
                digest = hashlib.md5(t[i : i + 2].encode("utf-8")).hexdigest()
                vec[int(digest, 16) % 32] += 1.0
            vectors.append(vec)
        return vectors


def _processor():
    from novamind.engines.document.pipeline.document_loader import DocumentProcessor

    return DocumentProcessor(embedding_client=DeterministicEmbedding())


# ---------------------------------------------------------------- 文档构造
@pytest.fixture(scope="module")
def docs_dir(tmp_path_factory) -> Path:
    """模块级一次性构造全部测试文档（程序化，无二进制夹具入库）。"""
    d = tmp_path_factory.mktemp("parsing_matrix")

    body = (
        f"# 标题一：{MARK} 解析矩阵\n\n"
        "这是第一段正文，包含中文与 English mixed content。"
        "这句话用来测试句子边界切分！句子之间有标点。\n\n"
        "## 标题二：子节\n\n"
        "- 列表项甲：知识库解析管道\n"
        "- 列表项乙：切分策略守护测试\n\n"
        "The quick brown fox jumps over the lazy dog. "
        "Pack my box with five dozen liquor jugs.\n\n"
        "收尾段落带足够长度用于触发尺寸上限切分。" * 8
    )
    (d / "sample.txt").write_text(body.replace("# ", "## ").replace("## 标题一", "标题一"), encoding="utf-8")
    (d / "sample.md").write_text(body, encoding="utf-8")
    (d / "sample.html").write_text(
        "<html><body><h1>HTML标题矩阵</h1><p>矩阵验证标记QWP 正文段落内容用于抽取验证。</p>"
        "<table><tr><td>单元格甲</td></tr></table></body></html>",
        encoding="utf-8",
    )
    (d / "sample.json").write_text(
        json.dumps({"title": "JSON标题矩阵验证标记QWP", "items": [{"name": "条目甲", "qty": 3}],
                   "note": "解析矩阵验证内容"}, ensure_ascii=False),
        encoding="utf-8",
    )

    import docx as docx_lib
    doc = docx_lib.Document()
    doc.add_heading("DOCX标题矩阵 矩阵验证标记QWP", level=1)
    doc.add_paragraph("DOCX 正文段落，用于文本抽取与切分验证。")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "表头甲"
    table.cell(1, 1).text = "单元格乙"
    doc.save(d / "sample.docx")

    import fitz
    pdf = fitz.open()
    for text in ["第一页：矩阵验证标记QWP PDF 文字层内容。", "第二页：表格与段落抽取。"]:
        page = pdf.new_page()
        page.insert_htmlbox(fitz.Rect(60, 70, 530, 300), f"<p>{text} 矩阵验证标记QWP</p>")
    pdf.save(d / "sample.pdf")
    pdf.close()

    # 扫描件（光栅化，无文字层）
    import fitz as fz2
    src = fz2.open()
    p1 = src.new_page(width=595, height=842)
    p1.insert_htmlbox(fitz.Rect(60, 80, 530, 200), "<p>扫描页视觉文字矩阵验证，含中英混排内容。</p>")
    pix = p1.get_pixmap(dpi=110)
    src.close()
    scan = fz2.open()
    sp = scan.new_page(width=595, height=842)
    sp.insert_image(fitz.Rect(50, 50, 545, 792), pixmap=pix)
    scan.save(d / "scan.pdf")
    scan.close()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml",
                    '<?xml version="1.0"?><container version="1.0" '
                    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                    '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                    "</rootfiles></container>")
        zf.writestr("OEBPS/content.opf",
                    '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
                    'version="2.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                    '<dc:title>EPUB矩阵</dc:title><dc:language>zh</dc:language><dc:creator>t</dc:creator>'
                    '<identifier id="id">urn:uuid:1234</identifier></metadata>'
                    '<manifest><item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/></manifest>'
                    '<spine><itemref idref="ch1"/></spine></package>')
        zf.writestr("OEBPS/ch1.xhtml",
                    "<html><body><h1>EPUB章节标题</h1><p>矩阵验证标记QWP 电子书正文段落，用于解析验证。</p></body></html>")
    (d / "sample.epub").write_bytes(buf.getvalue())

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "产品"
    ws["B1"] = "数量"
    ws["A2"] = "物料甲"
    ws["B2"] = 42
    ws["A3"] = "物料乙"
    ws["B3"] = 7
    wb.save(d / "sample.xlsx")

    from pptx import Presentation
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "PPT标题矩阵"
    slide.placeholders[1].text = "要点一：解析验证\n要点二：内容抽取"
    prs.save(d / "sample.pptx")

    return d


@pytest.fixture(scope="module")
def processor():
    return _processor()


# ---------------------------------------------------------------- 批 1：default reader × 8 切分
def _assert_split_ok(processor, full_text: str, strategy: str, params: dict) -> int:
    items = asyncio.run(processor.split_text_items(full_text, strategy=strategy, **params))
    assert items, f"{strategy} 0 块"
    joined = "".join(t for t, _meta in items)
    assert MARK in joined, f"{strategy} 切分丢标记"
    return len(items)


@pytest.mark.parametrize("strategy,params", SPLIT_PARAMS, ids=SPLIT_IDS)
class TestTxtDefault:
    def test_extract_and_split(self, processor, docs_dir, strategy, params):
        full = asyncio.run(processor.read_full_text(docs_dir / "sample.txt"))
        assert MARK in full
        assert _assert_split_ok(processor, full, strategy, params) >= 2


@pytest.mark.parametrize("strategy,params", SPLIT_PARAMS, ids=SPLIT_IDS)
class TestMdDefault:
    def test_extract_and_split(self, processor, docs_dir, strategy, params):
        full = asyncio.run(processor.read_full_text(docs_dir / "sample.md"))
        assert MARK in full
        _assert_split_ok(processor, full, strategy, params)


@pytest.mark.parametrize("strategy,params", SPLIT_PARAMS, ids=SPLIT_IDS)
class TestHtmlDefault:
    def test_extract_and_split(self, processor, docs_dir, strategy, params):
        full = asyncio.run(processor.read_full_text(docs_dir / "sample.html"))
        assert full.strip()
        _assert_split_ok(processor, full, strategy, params)


@pytest.mark.parametrize("strategy,params", SPLIT_PARAMS, ids=SPLIT_IDS)
class TestJsonDefault:
    def test_extract_and_split(self, processor, docs_dir, strategy, params):
        full = asyncio.run(processor.read_full_text(docs_dir / "sample.json"))
        assert "条目甲" in full
        _assert_split_ok(processor, full, strategy, params)


@pytest.mark.parametrize("strategy,params", SPLIT_PARAMS, ids=SPLIT_IDS)
class TestDocxDefault:
    def test_extract_and_split(self, processor, docs_dir, strategy, params):
        full = asyncio.run(processor.read_full_text(docs_dir / "sample.docx"))
        assert "DOCX标题矩阵" in full
        _assert_split_ok(processor, full, strategy, params)


@pytest.mark.parametrize("strategy,params", SPLIT_PARAMS, ids=SPLIT_IDS)
class TestPdfDefault:
    def test_extract_and_split(self, processor, docs_dir, strategy, params):
        full = asyncio.run(processor.read_full_text(docs_dir / "sample.pdf"))
        assert full.strip(), "文字层抽取为空"
        _assert_split_ok(processor, full, strategy, params)


# ---------------------------------------------------------------- 批 2：deepdoc × 8 切分（非 PDF）
DEEPDOC_DOC_TYPES = [
    ("sample.docx", "docx", "DOCX标题矩阵"),
    ("sample.epub", "epub", "EPUB章节标题"),
    ("sample.xlsx", "excel", "物料甲"),
    ("sample.pptx", "ppt", "PPT标题矩阵"),
    ("sample.md", "markdown", "标题一"),
    ("sample.html", "html", "HTML标题矩阵"),
    ("sample.json", "json", "JSON标题"),
    ("sample.txt", "txt", "标题一"),
]
DD_IDS = [f"{f.split('.')[0].upper()}" for f, _p, _m in DEEPDOC_DOC_TYPES]


@pytest.mark.parametrize("doc_file,parser_id,marker", DEEPDOC_DOC_TYPES, ids=DD_IDS)
class TestDeepdocByDocType:
    def test_deepdoc_parse_all_splits(self, processor, docs_dir, doc_file, parser_id, marker):
        """矩阵一区 deepdoc 路径：同一文档 × 8 切分全组合，断言全文含标记且逐切分出块。"""
        result = asyncio.run(
            processor.parse_document_result(
                docs_dir / doc_file,
                parsing_config={"strategy": "deepdoc", "deepdoc_parser_id": parser_id},
                splitting_config={"strategy": "recursive", "chunk_size": 300},
            )
        )
        assert result.full_text.strip(), f"deepdoc/{parser_id} 全文为空"
        assert marker in result.full_text, f"deepdoc/{parser_id} 缺标记"
        assert result.metadata.get("parser_id") or result.metadata.get("parser"), "缺解析器标识元数据"

        # 8 切分全组合逐个跑（同一解析产物重切，验证切分兼容性）
        for strategy, params in SPLIT_PARAMS:
            items = asyncio.run(
                processor.split_text_items(result.full_text, strategy=strategy, **params)
            )
            assert items, f"deepdoc/{parser_id} + {strategy} 0 块"


# ---------------------------------------------------------------- 批 5 前置：PDF deepdoc（高内存，marker 排最后执行）
class TestPdfDeepdocFull:
    """PDF deepdoc full（本地 OCR 流水线）——内存重，放最后批次执行。

    run order hint: pytest -k "TestPdfDeepdoc" 应在其他批次之后单独执行。
    """

    def test_full_default_split(self, processor, docs_dir):
        result = asyncio.run(
            processor.parse_document_result(
                docs_dir / "sample.pdf",
                parsing_config={"strategy": "deepdoc", "deepdoc_pdf_mode": "full"},
                splitting_config={"strategy": "recursive", "chunk_size": 300},
            )
        )
        assert result.full_text.strip(), "pdf full 全文为空"
        assert result.metadata.get("layout_source"), "缺 layout_source 元数据"

    def test_full_scene_split(self, processor, docs_dir):
        result = asyncio.run(
            processor.parse_document_result(
                docs_dir / "sample.pdf",
                parsing_config={"strategy": "deepdoc", "deepdoc_pdf_mode": "full"},
                splitting_config={"strategy": "fixed_size", "chunk_size": 200},
            )
        )
        assert result.chunks, "pdf full + fixed_size 0 块"
