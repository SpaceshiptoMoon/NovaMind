"""DOCX 文档读取器。"""
import hashlib
import os

from docx import Document
from novamind.shared.document.readers.base_reader import BaseReader
from novamind.shared.document.readers.executor import run_in_executor
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class DocxReader(BaseReader):
    """DOCX文档读取器"""

    def __init__(self):
        """初始化基类公共字段（编码列表、logger）。"""
        super().__init__()

    def _load_data_sync(self, file_path: str) -> list[dict[str, str]]:
        """用 python-docx 提取段落与表格文本并拼成整块。

        Raises:
            EncryptedDocumentError: OLE 头载荷（加密容器或旧版 .doc 改名）。
            MismatchedPayloadError: 非 OOXML 包（伪扩展名/损坏 zip）。
        """
        from novamind.engines.document.exceptions import (
            EncryptedDocumentError,
            MismatchedPayloadError,
        )

        # 载荷守卫：python-docx 对加密/伪格式文件抛误导性的
        # PackageNotFoundError，先按魔数分流出可直陈用户的失败原因
        with open(file_path, "rb") as fh:
            head = fh.read(8)
        if not head.startswith(b"PK\x03\x04"):
            if head.startswith(b"\xd0\xcf\x11\xe0"):
                raise EncryptedDocumentError(
                    "docx 文档已加密（打开密码或敏感度标签），请解密后上传",
                    format_name="docx",
                )
            raise MismatchedPayloadError(
                "docx 内容不是 OOXML 包（可能是旧版 .doc 改名或文件损坏）",
                format_name="docx",
            )

        documents = []
        # 打开/解析类失败一律上抛（红队 P2-2：吞成空列表会让损坏文件被
        # 上层误诊为「扫描件/空内容」，运维被引向错误的排查方向）
        doc = Document(file_path)

        # 提取所有段落的文本
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)

        # 获取表格中的文本
        for table in doc.tables:
            for row in table.rows:
                # 合并单元格去重：python-docx 对 spanned 网格位返回同一
                # cell 对象，不去重会让合并文本重复 N 遍污染全文（红队 P1-2）
                seen_tc = set()
                for cell in row.cells:
                    if id(cell._tc) in seen_tc:
                        continue
                    seen_tc.add(id(cell._tc))
                    full_text.append(cell.text)

        text = '\n'.join(full_text)

        if text.strip():
            documents.append({
                'text': text,
                'source': os.path.basename(file_path),
                'page': 1,
                'doc_id': f"docx_{hashlib.sha1(os.path.abspath(file_path).encode()).hexdigest()[:16]}",
                'type': 'docx'
            })
        return documents

    async def load_data(self, file_path: str) -> list[dict[str, str]]:
        """异步加载 DOCX 文本，重活转共享线程池避免阻塞事件循环。

        Args:
            file_path: DOCX 文件路径。

        Returns:
            单元素文档块列表（段落+表格全文拼合）；文档无可见文本时为空
            列表，加密/损坏/伪格式文件抛 ParsePayloadError 族异常。
        """
        return await run_in_executor(self._load_data_sync, file_path)