"""HTML 文档读取器。"""
import os

from bs4 import BeautifulSoup
from novamind.shared.document.readers.base_reader import BaseReader
from novamind.shared.document.readers.executor import run_in_executor
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class HTMLReader(BaseReader):
    """HTML文档读取器"""

    def __init__(self):
        """初始化基类公共字段（编码列表、logger）。"""
        super().__init__()

    def _read_with_encoding_sync(self, file_path: str) -> str:
        """按 utf-8/gbk/gb2312/latin-1/cp1252 顺序尝试解码，全部失败则忽略错误硬读。"""
        encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1', 'cp1252']

        for encoding in encodings:
            try:
                with open(file_path, encoding=encoding) as file:
                    content = file.read()
                return content
            except UnicodeDecodeError:
                continue

        # 如果所有编码都失败，使用错误处理方式
        with open(file_path, encoding='utf-8', errors='ignore') as file:
            return file.read()

    def _load_data_sync(self, file_path: str) -> list[dict[str, str]]:
        """用 BeautifulSoup 提取页面可见文本并拼成整块。"""
        documents = []
        try:
            # 使用支持多种编码的方法读取HTML文件
            content = self._read_with_encoding_sync(file_path)

            # 使用BeautifulSoup解析HTML
            soup = BeautifulSoup(content, 'html.parser')

            # 提取纯文本内容
            text = soup.get_text(separator='\n')

            if text.strip():
                documents.append({
                    'text': text,
                    'source': os.path.basename(file_path),
                    'page': 1,
                    'doc_id': f"html_{hash(file_path)}",
                    'type': 'html'
                })
        except Exception as e:
            logger.error("读取HTML文件失败", file_path=str(file_path), error=str(e))

        return documents

    async def load_data(self, file_path: str) -> list[dict[str, str]]:
        """异步加载 HTML 文本，重活转共享线程池避免阻塞事件循环。

        Args:
            file_path: HTML 文件路径。

        Returns:
            单元素文档块列表（页面可见文本），读取失败时返回空列表。
        """
        return await run_in_executor(self._load_data_sync, file_path)