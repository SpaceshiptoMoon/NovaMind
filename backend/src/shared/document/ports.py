"""跨 feature 文档摄入端口。

供 ``features/qa`` 等需要从上传文件（PDF/DOCX/...）提取文本的 feature 经抽象端口
调用知识库解析能力（``features/knowledge_space/pipeline/DocumentProcessor``），
切断 ``features.qa → features.knowledge_space.pipeline`` 直接 import 边。

端口为纯 Protocol（契约），不依赖任何 feature 实现；实现由
``features/knowledge_space/adapters/document_ingestion_adapter.py`` 提供。
"""
from __future__ import annotations

from typing import Any, List, Protocol, runtime_checkable


@runtime_checkable
class DocumentIngestionPort(Protocol):
    """文档摄入/文本提取端口：从文件路径按策略切分返回文本块列表。"""

    async def load_with_strategy(
        self,
        file_path: str,
        strategy: str = "recursive",
        chunk_size: int = 10000,
        chunk_overlap: int = 0,
    ) -> List[dict[str, Any]]:
        """按策略加载文件并切分，返回文本块 dict 列表（含 text/content 等键）。"""
        ...


__all__ = ["DocumentIngestionPort"]