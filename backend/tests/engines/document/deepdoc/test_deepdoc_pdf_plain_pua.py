"""DeepDoc plain 模式 PUA 归一回归测试。

RAGFlowPlainPdfParser.__call__ 逐行出口接入 normalize_pua_text 后：
PUA 占位字形不再透传进 plain 路径的全文/chunks（doc583 同根因旁路）。
用假 pdfplumber 驱动 __call__ 全流程，不依赖真实 PDF。
"""
from __future__ import annotations

import types

import pytest

pytestmark = pytest.mark.unit

E5D2 = ""  # 句读占位（前半）
E5CF = ""  # 句读占位（后半）

MODULE = "novamind.engines.document.integrations.deepdoc.parsers.pdf_plain"


def _install_fake_pdfplumber(monkeypatch, pages_text: list[str]):
    """装假 pdfplumber：open 返回逐页 extract_text 为预设文本的桩。

    直接 setattr 到 parser 模块（import pdfplumber 是模块属性引用），
    避免 sys.modules stub 在多测试间共享同一模块实例导致的闭包串扰。
    """
    import novamind.engines.document.integrations.deepdoc.parsers.pdf_plain as plain_mod

    fake = types.ModuleType("pdfplumber")

    class _FakePage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class _FakePdf:
        def __init__(self, pages):
            self.pages = [_FakePage(t) for t in pages]

    class _fake_open_ctx:
        def __init__(self, source):
            self._pdf = _FakePdf(pages_text)

        def __enter__(self):
            return self._pdf

        def __exit__(self, *exc):
            return False

    def fake_open(source):
        return _fake_open_ctx(source)

    fake.open = fake_open
    monkeypatch.setattr(plain_mod, "pdfplumber", fake)


def _load_parser():
    import importlib

    mod = importlib.import_module(MODULE)
    return mod.RAGFlowPlainPdfParser()


def test_plain_lines_pua_normalized(monkeypatch):
    """正例：CJK 夹间的成对句读占位被删除，不透传。"""
    _install_fake_pdfplumber(
        monkeypatch,
        ["本人呈交的学位论文是独立完成的研究成" + E5D2 + E5CF + "果。", "第二页正常内容"],
    )
    parser = _load_parser()
    sections, tables, outlines = parser(b"<fake pdf bytes>")
    assert [s[0] for s in sections] == [
        "本人呈交的学位论文是独立完成的研究成果。",
        "第二页正常内容",
    ]
    assert tables == []


def test_plain_lines_clean_text_unchanged(monkeypatch):
    """反例：干净文本逐字不变（无 PUA 不做任何变换）。"""
    raw = "两类低秩矩阵重构模型及其应用探索 ２０１８年４月"
    _install_fake_pdfplumber(monkeypatch, [raw])
    parser = _load_parser()
    sections, _, _ = parser(b"<fake pdf bytes>")
    assert [s[0] for s in sections] == [raw]
