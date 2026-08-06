"""
DocumentIngestionPort 宿主适配器，桥接 pipeline.DocumentProcessor 提供文件解析能力。
"""
from __future__ import annotations

from typing import Any, List

from novamind.features.knowledge_space.pipeline import DocumentProcessor
from novamind.shared.document.ports import DocumentIngestionPort


class HostDocumentIngestionPort:
    """``DocumentIngestionPort`` 宿主实现：委托 ``DocumentProcessor``。"""

    __slots__ = ("_processor",)

    def __init__(self, processor: DocumentProcessor | None = None) -> None:
        self._processor = processor or DocumentProcessor()

    async def load_with_strategy(
        self,
        file_path: str,
        strategy: str = "recursive",
        chunk_size: int = 10000,
        chunk_overlap: int = 0,
    ) -> List[dict[str, Any]]:
        return await self._processor.load_with_strategy(
            file_path,
            strategy=strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )


def as_document_ingestion_port(
    processor: DocumentProcessor | None = None,
) -> DocumentIngestionPort:
    """工厂：构造 ``HostDocumentIngestionPort`` 并以 ``DocumentIngestionPort`` 返回。"""
    return HostDocumentIngestionPort(processor)


def is_document_ingestion_port(obj: object) -> bool:
    """``runtime_checkable`` isinstance 校验。"""
    return isinstance(obj, DocumentIngestionPort)