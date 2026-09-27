"""extract_pdf_outlines 书签标题 PUA 归一回归测试。

PDF 书签 /Title 直出本是低概率注入面（书签串不经字体 CMap），但出口统一
归一后：异常码点不透传进 metadata["outlines"]，干净标题逐字不变。
用假 pypdf 桩驱动，不依赖真实 PDF。
"""
from __future__ import annotations

import types

import pytest

pytestmark = pytest.mark.unit

E5D2 = "\ue5d2"  # 句读占位（前半）
E5CF = "\ue5cf"  # 句读占位（后半）

MODULE = "novamind.engines.document.integrations.deepdoc.parsers.upstream.utils"


def _install_fake_pypdf(monkeypatch, titles: list[str]):
    """setattr 假 PdfReader 到 utils 模块（模块属性引用，测试间无串扰）。"""
    import novamind.engines.document.integrations.deepdoc.parsers.upstream.utils as utils_mod

    class _FakePdf:
        def __init__(self, source):
            self.outline = [{"/Title": t, "page": i} for i, t in enumerate(titles)]

        # 真 PdfReader 支持上下文管理器，extract_pdf_outlines 用 with 打开
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_destination_page_number(self, node):
            return node["page"]

    # 真 utils._import_pdf_reader 返回 PdfReader 类本身，随后被 pdf2_read(source) 调用
    monkeypatch.setattr(utils_mod, "_import_pdf_reader", lambda: _FakePdf)


def test_outlines_pua_normalized(monkeypatch):
    """正例：CJK 夹间的句读占位被删除，不透传。"""
    _install_fake_pypdf(monkeypatch, ["第一" + E5D2 + E5CF + "章 总论", "附录"])
    import importlib

    mod = importlib.import_module(MODULE)
    outlines = mod.extract_pdf_outlines("fake.pdf")
    assert outlines[0][0] == "第一章 总论"
    assert outlines[1][0] == "附录"


def test_outlines_clean_text_unchanged(monkeypatch):
    """反例：干净标题逐字不变。"""
    _install_fake_pypdf(monkeypatch, ["两类低秩矩阵重构模型及其应用探索"])
    import importlib

    mod = importlib.import_module(MODULE)
    outlines = mod.extract_pdf_outlines("fake.pdf")
    assert outlines[0][0] == "两类低秩矩阵重构模型及其应用探索"
