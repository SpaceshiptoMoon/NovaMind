"""文档切分器基类。"""
from abc import ABC, abstractmethod


class BaseSplitter(ABC):
    """文档切分器基类"""

    @abstractmethod
    async def split(self, documents: list[dict[str, str]]) -> list[dict[str, str]]:
        """切分文档。

        Args:
            documents: 页/段 dict 列表（content 或 text 键承载正文）。

        Returns:
            切分后的文档块列表（dict 形状同输入）。
        """
        pass