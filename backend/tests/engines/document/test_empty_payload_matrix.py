"""空文档载荷矩阵：各格式"结构合法但内容为空"的解析器层行为契约。

背景（doc 952 泛化）：空 OFD/纯图 PDF/空 DOCX 这类"解析器不崩但产出 0 字符"
的载荷，最终由管线空文本守卫按格式分化文案（见
test_pipeline_parse_failure_visibility.py）；本矩阵锁定更底层的不变量——

- 解析器层对空载荷**不崩**（不裸栈、不 IndexError）：要么返回（full_text 为空
  或仅结构残留），要么抛显式业务异常（如空 zip 容器的 MismatchedPayloadError）；
- 0 字符语义明确：管线守卫据此判定"文档无正文"，行为可预期。

覆盖形态：0 字节 / 全空白 / 仅结构性标签 / 空正文容器 / 空白页 PDF / 空 OFD /
空 zip 容器。
"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.exceptions import MismatchedPayloadError
from novamind.engines.document.integrations.deepdoc.core.runtime_parser import DeepDocParser

pytestmark = pytest.mark.unit


def _empty_ofd() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("OFD.xml", '<ofd:OFDDoc xmlns:ofd="http://www.ofdspec.org/2016"/>')
        zf.writestr(
            "Doc_0/Document.xml",
            '<ofd:Document xmlns:ofd="http://www.ofdspec.org/2016">'
            '<ofd:Pages><ofd:Page ID="1"/></ofd:Pages></ofd:Document>',
        )
    return buf.getvalue()


def _empty_pdf() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _empty_docx() -> bytes:
    import docx

    buf = io.BytesIO()
    docx.Document().save(buf)
    return buf.getvalue()


_CASES = {
    # (payload bytes, deepdoc file_type)
    "txt_0byte": (b"", "txt"),
    "txt_whitespace": (b"   \n\t  \n", "txt"),
    "md_only_headings": (b"# \n\n##\n", "md"),
    "json_empty_object": (b"{}", "json"),
    "html_no_body_text": (
        b"<html><head><style>body{color:red}</style></head><body>   </body></html>",
        "html",
    ),
    "docx_no_runs": (_empty_docx(), "docx"),
    "pdf_blank_page": (_empty_pdf(), "pdf"),
    "ofd_no_text_code": (_empty_ofd(), "ofd"),
}


@pytest.mark.parametrize("name", sorted(_CASES))
def test_empty_payload_does_not_crash(name):
    """空载荷矩阵：解析器层不裸栈——正常返回（内容为空/结构残留）或显式业务异常。"""
    payload, file_type = _CASES[name]
    result = asyncio_run_parse(payload, file_type)
    assert result is not None, f"{name}: 解析器静默返回 None"
    # full_text 允许为空或仅结构残留（如 md 空标题行），不允许裸栈崩溃
    assert isinstance(result.full_text, str)


def asyncio_run_parse(payload: bytes, file_type: str):
    import asyncio

    return asyncio.run(
        DeepDocParser().parse_bytes(
            payload, file_type=file_type,
            parsing_config={}, splitting_config={"chunk_size": 500},
        )
    )


def test_empty_zip_container_rejected_by_guard():
    """空 zip 容器（0 成员）→ MismatchedPayloadError：无成员的文档包按损坏防御拒收。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass
    with pytest.raises(MismatchedPayloadError):
        asyncio_run_parse(buf.getvalue(), "zip")


@pytest.mark.parametrize(
    "name, file_type",
    [("txt_0byte", "txt"), ("txt_whitespace", "txt"), ("docx_no_runs", "docx"),
     ("pdf_blank_page", "pdf"), ("ofd_no_text_code", "ofd")],
)
def test_empty_payload_yields_zero_chars(name, file_type):
    """核心空形态（无任何结构性残留）产出 0 字符——管线空文本守卫的触发前提。"""
    payload, ft = _CASES[name]
    result = asyncio_run_parse(payload, ft)
    assert (result.full_text or "").strip() == "", f"{name}: 应产出 0 字符"
