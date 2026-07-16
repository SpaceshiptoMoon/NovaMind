from abc import ABC, abstractmethod
from typing import List, Dict


class BaseReader(ABC):
    """文档读取器基类"""

    @abstractmethod
    async def load_data(self, file_path: str) -> List[Dict[str, str]]:
        """从文件加载数据，返回文档块列表"""
        pass