"""文档读取器基类。"""
from abc import ABC, abstractmethod


class BaseReader(ABC):
    """文档读取器基类"""

    @abstractmethod
    async def load_data(self, file_path: str) -> list[dict[str, str]]:
        """从文件加载数据，返回结构化文档块列表。

        Args:
            file_path: 文档文件在磁盘上的路径。

        Returns:
            文档块列表，每块为 dict（含 text、source、page、doc_id、type 等键）；读取失败返回空列表。
        """
        pass