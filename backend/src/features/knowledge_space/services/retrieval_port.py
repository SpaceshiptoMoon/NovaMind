"""检索端口（消费方契约）

批次 2 接缝：``qa`` / ``deep_research`` 等消费方依赖 ``RetrievalPort`` 抽象，而非直接
import ``SearchService``。宿主在 ``adapters/retrieval_adapter.py`` 提供 ``HostRetrievalPort``
实现（包 ``SearchService``）。

端口只暴露消费方实际需要的方法：``search``（含权限 + 配置 + 改写 + LLM 生成的完整检索响应）。
纯检索 ``RetrievalEngine.retrieve_raw`` 是引擎内部能力，不在此端口暴露——需要纯检索的进阶
消费方在批次 6 抽包后再经独立端口接入。
"""
from typing import Any, Dict, Protocol, runtime_checkable

from novamind.features.knowledge_space.schemas.search_schema import SearchRequest


@runtime_checkable
class RetrievalPort(Protocol):
    """检索服务端口（消费方依赖此抽象，宿主提供实现）。"""

    async def search(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        request: SearchRequest,
    ) -> Dict[str, Any]:
        """执行检索，返回完整响应 dict（results / answer / rewritten_queries 等）。

        实现负责权限校验、模式可用性、查询改写、模型客户端解析、LLM 回答生成。
        """
        ...