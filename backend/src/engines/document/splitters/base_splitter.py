"""文档切分器基类。"""
from abc import ABC, abstractmethod


class BaseSplitter(ABC):
    """文档切分器基类"""

    @abstractmethod
    async def split(self, documents: list[dict[str, str]]) -> list[dict[str, str]]:
        """切分文档"""
        pass