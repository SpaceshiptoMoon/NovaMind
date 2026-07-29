"""检索端口宿主适配器

``HostRetrievalPort`` 包装 ``SearchService``，实现 ``RetrievalPort``。消费方（qa /
deep_research）依赖 ``RetrievalPort`` 抽象，由依赖注入提供本实现——从而与 ``SearchService``
具体类解耦，为批次 6 引擎抽包留出接缝。
"""
from typing import Any, Dict

from novamind.features.knowledge_space.schemas.search_schema import SearchRequest
from novamind.features.knowledge_space.services.retrieval_port import RetrievalPort
from novamind.features.knowledge_space.services.search_service import SearchService


class HostRetrievalPort:
    """``RetrievalPort`` 宿主实现：委托被包装的 ``SearchService``。"""

    def __init__(self, search_service: SearchService) -> None:
        self._search_service = search_service

    @property
    def search_service(self) -> SearchService:
        """暴露被包装的 SearchService（供需要其专有方法的宿主代码使用）。"""
        return self._search_service

    async def search(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        request: SearchRequest,
    ) -> Dict[str, Any]:
        return await self._search_service.search(
            space_id=space_id,
            kb_id=kb_id,
            user_id=user_id,
            request=request,
        )


def as_retrieval_port(search_service: SearchService) -> RetrievalPort:
    """把 SearchService 适配为 RetrievalPort（便捷工厂）。"""
    return HostRetrievalPort(search_service)  # type: ignore[return-value]


def is_retrieval_port(obj: Any) -> bool:
    """运行时判定是否实现 RetrievalPort（Protocol 为 runtime_checkable）。"""
    return isinstance(obj, RetrievalPort)


__all__ = [
    "HostRetrievalPort",
    "as_retrieval_port",
    "is_retrieval_port",
]