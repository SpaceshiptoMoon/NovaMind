"""纯文本文件读取器。"""
import hashlib
import os

from novamind.shared.document.readers.base_reader import BaseReader
from novamind.shared.document.readers.executor import run_in_executor
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class TxtReader(BaseReader):
    """TXT文档读取器"""

    def __init__(self):
        """初始化基类公共字段（编码列表、logger）。"""
        super().__init__()

    def _read_with_encoding_sync(self, file_path: str) -> str:
        """BOM 感知解码（实现见 BaseReader.decode_text_file——红队 P1-1 统一收口）。"""
        return self.decode_text_file(file_path)

    def _load_data_sync(self, file_path: str) -> list[dict[str, str]]:
        """读取纯文本文件并拼成整块。"""
        documents = []
        try:
            # 使用支持多种编码的方法读取TXT文件
            text = self._read_with_encoding_sync(file_path)

            if text.strip():
                documents.append({
                    'text': text,
                    'source': os.path.basename(file_path),
                    'page': 1,
                    'doc_id': f"txt_{hashlib.sha1(os.path.abspath(file_path).encode()).hexdigest()[:16]}",
                    'type': 'txt'
                })
        except (FileNotFoundError, PermissionError, IsADirectoryError):
            # 打开类失败上抛（红队 P2-2：吞成空列表会让损坏/无权限文件被
            # 上层误诊为「扫描件/空内容」，运维被引向错误的排查方向）
            raise
        except Exception as e:
            logger.error("读取TXT文件失败", file_path=str(file_path), error=str(e))

        return documents

    async def load_data(self, file_path: str) -> list[dict[str, str]]:
        """异步加载纯文本，重活转共享线程池避免阻塞事件循环。

        Args:
            file_path: 文本文件路径。

        Returns:
            单元素文档块列表（文件全文），读取失败时返回空列表。
        """
        return await run_in_executor(self._load_data_sync, file_path)