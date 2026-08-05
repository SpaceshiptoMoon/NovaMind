from abc import ABC, abstractmethod
from typing import List, Dict


class BaseSplitter(ABC):
    """文档切分器基类"""

    @abstractmethod
    async def split(self, documents: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """切分文档"""
        pass