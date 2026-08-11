"""跨 feature 文档读取器（PDF / DOCX / TXT / HTML / MD），被 app / qa / knowledge_space 复用。"""
from novamind.shared.document.readers.base_reader import BaseReader
from novamind.shared.document.readers.pdf_reader import PDFReader
from novamind.shared.document.readers.docx_reader import DocxReader
from novamind.shared.document.readers.txt_reader import TxtReader
from novamind.shared.document.readers.html_reader import HTMLReader
from novamind.shared.document.readers.md_reader import MarkdownReader
from novamind.shared.document.readers.executor import (
    get_shared_executor,
    run_in_executor,
    shutdown_executor,
)

__all__ = [
    "BaseReader",
    "PDFReader",
    "DocxReader",
    "TxtReader",
    "HTMLReader",
    "MarkdownReader",
    "get_shared_executor",
    "run_in_executor",
    "shutdown_executor",
]
