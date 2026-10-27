"""eml/msg/ofd 解析器回归：邮件头正文/附件清单/OFD 文本层/守卫路径。"""
import asyncio
import sys
import zipfile
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit

from novamind.engines.document.exceptions import MismatchedPayloadError
from novamind.engines.document.integrations.deepdoc.core.runtime_parser import (
    DeepDocParser,
)
from novamind.engines.document.integrations.deepdoc.parsers.eml import RAGFlowEmlParser
from novamind.engines.document.integrations.deepdoc.parsers.msg import RAGFlowMsgParser
from novamind.engines.document.integrations.deepdoc.parsers.ofd import RAGFlowOfdParser

_OFD_NS = "http://www.ofdspec.org/2016"


def _build_eml() -> bytes:
    msg = EmailMessage()
    msg["From"] = "张三 <zhangsan@example.com>"
    msg["To"] = "李四 <lisi@example.com>"
    msg["Subject"] = "季度预算审批"
    msg["Date"] = "Mon, 27 Oct 2026 10:00:00 +0800"
    msg.set_content("请审批附件中的季度预算。\n预算总额 120 万。")
    msg.add_attachment(
        b"fake-xlsx-bytes",
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="Q4预算.xlsx",
    )
    return msg.as_bytes()


def test_eml_header_body_attachment_extracted():
    """邮件头（RFC 2047 编码解码）/正文/附件清单全部进产物。"""
    sections = RAGFlowEmlParser()(_build_eml())
    joined = "\n".join(sections)
    assert "季度预算审批" in joined and "张三" in joined
    assert "Q4预算.xlsx" in joined, "附件清单应列出文件名"
    assert "预算总额 120 万" in joined
    assert b"fake-xlsx-bytes"[:4] not in joined.encode(), "附件内容不应混入正文"


def test_eml_html_body_uses_html_parser():
    """无纯文本部分时 HTML 正文经 html 解析器转块（噪音剔除同链）。"""
    msg = EmailMessage()
    msg["Subject"] = "HTML 正文邮件"
    msg["From"] = "a@b.c"
    msg.add_alternative(
        "<html><body><p>正文段落内容甲。</p><style>body{color:red}</style></body></html>",
        subtype="html",
    )
    sections = RAGFlowEmlParser()(msg.as_bytes())
    joined = "\n".join(sections)
    assert "正文段落内容甲" in joined
    assert "color:red" not in joined, "style 噪音应被剔除"


def test_msg_non_ole_rejected():
    """非 OLE 载荷的伪 msg → MismatchedPayloadError。"""
    with pytest.raises(MismatchedPayloadError):
        RAGFlowMsgParser()(b"plain text not msg")


def _content_xml(texts: list[str]) -> str:
    body = "".join(
        f'<ofd:TextObject ID="{i}"><ofd:TextCode>{t}</ofd:TextCode></ofd:TextObject>'
        for i, t in enumerate(texts)
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<ofd:Page xmlns:ofd="{_OFD_NS}"><ofd:Content>'
        f"<ofd:PageBlock>{body}</ofd:PageBlock></ofd:Content></ofd:Page>"
    )


def _build_ofd() -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("OFD.xml", f'<ofd:OFDDoc xmlns:ofd="{_OFD_NS}"/>')
        zf.writestr("Doc_0/Document.xml", f'<ofd:Document xmlns:ofd="{_OFD_NS}"/>')
        zf.writestr("Doc_0/Pages/Page_0/Content.xml", _content_xml(["第一页：项目立项申请", "申请人：王五"]))
        zf.writestr("Doc_0/Pages/Page_1/Content.xml", _content_xml(["第二页：预算明细"]))
    return buf.getvalue()


def test_ofd_text_layer_extracted_in_page_order():
    """OFD 文字层逐页提取，页序按 Page_N 数字序（非字典序）。"""
    sections = RAGFlowOfdParser()(_build_ofd())
    joined = "\n".join(sections)
    assert "项目立项申请" in joined and "预算明细" in joined
    assert joined.index("第一页") < joined.index("第二页"), "页序错乱"


def test_ofd_non_zip_rejected():
    """非 zip 载荷 → MismatchedPayloadError。"""
    with pytest.raises(MismatchedPayloadError):
        RAGFlowOfdParser()(b"junk-not-zip")


@pytest.mark.parametrize("file_type", ["eml", "msg", "ofd"])
def test_unsupported_payload_raises_clearly(file_type):
    """runtime 层路由：垃圾载荷经新格式入口抛显式异常（非裸栈）。"""
    with pytest.raises((MismatchedPayloadError, ValueError)):
        asyncio.run(
            DeepDocParser().parse_bytes(
                b"garbage-payload-123", file_type=file_type,
                parsing_config={}, splitting_config={"chunk_size": 500},
            )
        )
