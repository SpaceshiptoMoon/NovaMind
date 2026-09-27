"""PDFReader（pypdf 通用阅读器）PUA 归一回归测试。

pypdf extract_text 对未映射 CID 字体同样产出 PUA（与 deepdoc 文字层同根因），
页级出口接入 normalize_pua_text 后不再透传。monkeypatch pypdf 驱动，不依赖真实 PDF。
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

E5D2 = ""  # 句读占位（前半）
E5CF = ""  # 句读占位（后半）

MODULE = "novamind.shared.document.readers.pdf_reader"


def _install_fake_pypdf(monkeypatch, pages_text: list[str]):
    """setattr 假 PyPdfReader 到 reader 模块（模块属性引用，测试间无串扰）。"""
    import novamind.shared.document.readers.pdf_reader as reader_mod

    class _FakePage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class _FakePdf:
        def __init__(self, path):
            self.pages = [_FakePage(t) for t in pages_text]

    monkeypatch.setattr(reader_mod, "PyPdfReader", _FakePdf)


def _load_reader():
    import importlib

    mod = importlib.import_module(MODULE)
    return mod.PDFReader()


def test_pdf_reader_pua_normalized(monkeypatch):
    """正例：页文本里的成对句读占位被删除。"""
    _install_fake_pypdf(
        monkeypatch,
        ["研究成果" + E5D2 + E5CF + "已在文中标明", "结束"],
    )
    docs = _load_reader()._load_data_sync("fake.pdf")
    assert len(docs) == 1
    # 两页各追加一个 \n
    assert docs[0]["text"] == "研究成果已在文中标明\n结束\n"


def test_pdf_reader_clean_text_unchanged(monkeypatch):
    """反例：干净文本（含全角字符）逐字不变。"""
    raw = "２０１８年４月 两类低秩矩阵重构模型"
    _install_fake_pypdf(monkeypatch, [raw])
    docs = _load_reader()._load_data_sync("fake.pdf")
    assert len(docs) == 1
    assert docs[0]["text"] == raw + "\n"
