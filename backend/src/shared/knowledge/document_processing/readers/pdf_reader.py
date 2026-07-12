import os
from typing import List, Dict
from novamind.shared.knowledge.document_processing.readers.base_reader import BaseReader
from novamind.shared.knowledge.document_processing.readers.executor import run_in_executor
from novamind.core.middleware.structured_logging import get_logger
from PyPDF2 import PdfReader as PyPdfReader

logger = get_logger(__name__)


class PDFReader(BaseReader):
    """PDF文档读取器"""

    def __init__(self):
        super().__init__()

    def _load_data_sync(self, file_path: str) -> List[Dict[str, str]]:
        """
        同步读取 PDF 文件（在线程池中执行）
        :param file_path: PDF文件路径
        :return: 文档块列表
        """
        documents = []
        try:
            # 使用PyPDF2读取PDF
            pdf = PyPdfReader(file_path)

            # 提取所有页面的文本
            text = ""
            page_numbers = []
            for i, page in enumerate(pdf.pages):
                text += page.extract_text() + "\n"
                page_numbers.append(i + 1)

            if text.strip():
                documents.append({
                    'text': text,
                    'source': os.path.basename(file_path),
                    'page': 1,
                    'doc_id': f"pdf_{hash(file_path)}",
                    'type': 'pdf'
                })
        except Exception as e:
            logger.error("读取PDF文件失败", file_path=str(file_path), error=str(e))

        return documents

    async def load_data(self, file_path: str) -> List[Dict[str, str]]:
        """
        从PDF文件加载数据（异步，在共享线程池中执行）
        :param file_path: PDF文件路径
        :return: 文档块列表，每个文档块包含文本和其他元数据
        """
        return await run_in_executor(self._load_data_sync, file_path)