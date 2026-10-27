"""PDF 文档读取器。"""
import hashlib
import os

from novamind.shared.document.readers.base_reader import BaseReader
from novamind.shared.document.readers.executor import run_in_executor
from novamind.shared.logging import get_logger
from novamind.shared.utils.text_utils import normalize_pua_text
from pypdf import PdfReader as PyPdfReader

logger = get_logger(__name__)


class PDFReader(BaseReader):
    """PDF文档读取器"""

    def __init__(self):
        """初始化基类公共字段（编码列表、logger）。"""
        super().__init__()

    def _load_data_sync(self, file_path: str) -> list[dict[str, str]]:
        """用 pypdf 提取 PDF 全文（拼成一整块，含逐页 PUA 归一）。

        Raises:
            EncryptedDocumentError: 打开密码保护的 PDF。
        """
        from novamind.engines.document.exceptions import EncryptedDocumentError

        documents = []
        # 打开/解析类失败一律上抛（红队 P2-2：吞成空列表会让损坏文件被
        # 上层误诊为「扫描件/空内容」，运维被引向错误的排查方向）
        # 使用 pypdf（PyPDF2 官方继任者，API 兼容）读取 PDF
        pdf = PyPdfReader(file_path)
        if pdf.is_encrypted:
            # 权限密码（空用户密码可开）pypdf 已自动解密，is_encrypted 仍为
            # True 但可读；仅当解密失败（用户密码）时拦
            if not pdf.decrypt(""):
                raise EncryptedDocumentError(
                    "PDF 文档已加密（打开密码保护），请解密后上传",
                    format_name="pdf",
                )

        # 提取所有页面的文本
        text = ""
        page_numbers = []
        for i, page in enumerate(pdf.pages):
            # pypdf 对未映射 CID 字体同样产出 PUA 字符（与 deepdoc 文字层
            # 同根因），页级出口归一（语境化规则与 deepdoc 两条路径共用）。
            text += normalize_pua_text(page.extract_text()) + "\n"
            page_numbers.append(i + 1)

        if text.strip():
            documents.append({
                'text': text,
                'source': os.path.basename(file_path),
                'page': 1,
                'doc_id': f"pdf_{hashlib.sha1(os.path.abspath(file_path).encode()).hexdigest()[:16]}",
                'type': 'pdf'
            })
        return documents

    async def load_data(self, file_path: str) -> list[dict[str, str]]:
        """异步加载 PDF 全文，重活转共享线程池避免阻塞事件循环。

        Args:
            file_path: PDF 文件路径。

        Returns:
            单元素文档块列表（全文拼合）；文档无文字层（扫描件）时为空
            列表，加密/损坏文件抛 ParsePayloadError 族或底层异常。
        """
        return await run_in_executor(self._load_data_sync, file_path)