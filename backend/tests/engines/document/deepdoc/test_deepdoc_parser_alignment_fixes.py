"""DeepDoc 非 PDF 解析器对齐修复的回归测试。

覆盖：
- figure: OCR 入参必须是 numpy（PIL 传到底层会 AttributeError）
- excel: 单表异常不应导致整个工作簿解析失败
- html: 超长 atom 字符窗口回退
- markdown: 围栏代码块不被 # 注释行误判标题、不被空行切碎（vendored 上游）
"""
import numpy as np
import pytest

pytestmark = pytest.mark.unit


# ---------------- figure ----------------

def test_figure_ocr_receives_numpy_not_pil(monkeypatch):
    """figure._extract_text_with_ocr 必须把 PIL 转 numpy 再喂 OCR.detect/recognize，
    否则底层 TextDetector 的 ori_im.shape / cv2.warpPerspective 会 AttributeError。"""
    from novamind.engines.document.integrations.deepdoc.parsers import figure as figure_mod
    from PIL import Image

    received = {}

    class _FakeOCR:
        def __init__(self, *a, **kw):
            pass

        def detect(self, img, device_id=None):
            received["detect_type"] = type(img)
            # 返回一个 quad 供 recognize 路径走
            return [((np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=np.float32)), ("", 0))]

        def recognize(self, ori_im, box, device_id=None):
            received["recognize_type"] = type(ori_im)
            return "line"

    monkeypatch.setattr(figure_mod, "OCR", _FakeOCR)
    parser = figure_mod.RAGFlowFigureParser()
    img = Image.new("RGB", (32, 32), "white")
    lines, boxes = parser._extract_text_with_ocr(img)
    assert received["detect_type"] is np.ndarray
    assert received["recognize_type"] is np.ndarray
    assert lines == ["line"]


def test_figure_ocr_detect_failure_degrades_gracefully(monkeypatch):
    """OCR.detect 抛异常时不应炸掉整个图片解析，应降级返回 ([], [])。"""
    from novamind.engines.document.integrations.deepdoc.parsers import figure as figure_mod
    from PIL import Image

    class _BadOCR:
        def __init__(self, *a, **kw):
            pass

        def detect(self, img, device_id=None):
            raise RuntimeError("model boom")

        def recognize(self, *a, **kw):
            return ""

    monkeypatch.setattr(figure_mod, "OCR", _BadOCR)
    parser = figure_mod.RAGFlowFigureParser()
    lines, boxes = parser._extract_text_with_ocr(Image.new("RGB", (16, 16), "white"))
    assert lines == []
    assert boxes == []


# ---------------- excel ----------------

def test_excel_call_skips_bad_sheet(monkeypatch):
    """单个 sheet 抽行异常时，__call__ 应跳过该 sheet 返回其余 sheet 的行，而不是整本失败。"""
    from novamind.engines.document.integrations.deepdoc.parsers import excel as excel_mod

    class _FakeWS:
        pass

    class _FakeWB:
        sheetnames = ["good", "bad"]

        def __getitem__(self, name):
            return _FakeWS()

    def _good_rows(ws):
        # 仅 good sheet 返回数据；通过对象 id 区分
        if ws is _FakeWS:  # 两个 sheet 同类，用侧栏标记
            raise AssertionError("不应走到这里")
        return []

    # 用闭包区分两个 sheet
    call_state = {"good_done": False}

    def _rows_limited(ws):
        if not call_state["good_done"]:
            call_state["good_done"] = True
            # 第一个 sheet（good）返回一行数据
            class _Cell:
                value = "v"
            class _Row:
                def __iter__(self):
                    return iter([_Cell()])
            return [_Row(), _Row()]
        # 第二个 sheet（bad）抛异常
        raise RuntimeError("bad sheet")

    monkeypatch.setattr(excel_mod.RAGFlowExcelParser, "_load_excel_to_workbook", staticmethod(lambda f: _FakeWB()))
    monkeypatch.setattr(excel_mod.RAGFlowExcelParser, "_get_rows_limited", staticmethod(lambda ws: _rows_limited(ws)))

    parser = excel_mod.RAGFlowExcelParser()
    # good sheet 有 1 数据行；bad sheet 抛异常被跳过
    rows = parser.__call__(b"fake")
    assert rows  # good sheet 的行保留了
    # 不应抛异常


# ---------------- html ----------------

def test_html_split_oversized_block_splits_long_atom():
    """单个 atom 超过 token 预算（长无空格串）应按字符窗口切，不应整段成一个超大 chunk。"""
    from novamind.engines.document.integrations.deepdoc.parsers.html import RAGFlowHtmlParser

    # URL 无空格无 CJK，整体是一个 atom；rag_tokenizer 切成 6 token。
    # chunk_token_num=4 < 6 → 触发字符窗口回退。
    long_atom = "https://example.com/a/b/c"
    assert RAGFlowHtmlParser._token_count(long_atom) > 4
    pieces = RAGFlowHtmlParser._split_oversized_block(long_atom, chunk_token_num=4)
    assert len(pieces) > 1
    assert all(len(p) <= 4 for p in pieces)
    assert "".join(pieces) == long_atom


# ---------------- markdown ----------------

def test_markdown_code_block_not_split_by_comment_or_blank():
    """围栏代码块内的 # 注释行不应被误判为标题，代码块不应被空行切碎。"""
    from novamind.engines.document.integrations.deepdoc.parsers.upstream.markdown_parser import (
        MarkdownElementExtractor,
        RAGFlowMarkdownParser,
    )

    md = (
        "# Title\n\n"
        "intro paragraph.\n\n"
        "```python\n"
        "# this is a comment not a title\n"
        "import os\n"
        "\n"
        "os.getcwd()\n"
        "```\n\n"
        "tail paragraph.\n"
    )
    text_without_tables, _tables = RAGFlowMarkdownParser().extract_tables_and_remainder(md, separate_tables=False)
    sections = MarkdownElementExtractor(text_without_tables).extract_elements()
    # 代码块应作为单个 section 完整保留
    code_sections = [s for s in sections if s.strip().startswith("```")]
    assert len(code_sections) == 1
    code = code_sections[0]
    assert "# this is a comment not a title" in code
    assert "import os" in code
    assert "os.getcwd()" in code
    # 代码块以 ``` 闭合
    assert code.rstrip().endswith("```")


def test_markdown_no_border_table_extracted():
    """无边界 Markdown 表格（行首不以 | 开头）应被抽到 tables，不散落正文。"""
    from novamind.engines.document.integrations.deepdoc.parsers.upstream.markdown_parser import (
        RAGFlowMarkdownParser,
    )

    md = "A | B\n--- | ---\n1 | 2\n"
    _text, tables = RAGFlowMarkdownParser().extract_tables_and_remainder(md, separate_tables=False)
    assert len(tables) == 1