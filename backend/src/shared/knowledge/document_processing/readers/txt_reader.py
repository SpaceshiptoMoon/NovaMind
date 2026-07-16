import os
from typing import List, Dict
from novamind.shared.knowledge.document_processing.readers.base_reader import BaseReader
from novamind.shared.knowledge.document_processing.readers.executor import run_in_executor
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class TxtReader(BaseReader):
    """TXT文档读取器"""

    def __init__(self):
        super().__init__()

    def _read_with_encoding_sync(self, file_path: str) -> str:
        """
        尝试多种编码格式读取文件（同步版本，在线程池中执行）
        """
        encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1', 'cp1252']

        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as file:
                    text = file.read()
                return text
            except UnicodeDecodeError:
                continue

        # 如果所有编码都失败，使用错误处理方式
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
            return file.read()

    def _load_data_sync(self, file_path: str) -> List[Dict[str, str]]:
        """
        同步读取 TXT 文件（在线程池中执行）
        :param file_path: TXT文件路径
        :return: 文档块列表
        """
        documents = []
        try:
            # 使用支持多种编码的方法读取TXT文件
            text = self._read_with_encoding_sync(file_path)

            if text.strip():
                documents.append({
                    'text': text,
                    'source': os.path.basename(file_path),
                    'page': 1,
                    'doc_id': f"txt_{hash(file_path)}",
                    'type': 'txt'
                })
        except Exception as e:
            logger.error("读取TXT文件失败", file_path=str(file_path), error=str(e))

        return documents

    async def load_data(self, file_path: str) -> List[Dict[str, str]]:
        """
        从TXT文件加载数据（异步，在共享线程池中执行）
        :param file_path: TXT文件路径
        :return: 文档块列表，每个文档块包含文本和其他元数据
        """
        return await run_in_executor(self._load_data_sync, file_path)