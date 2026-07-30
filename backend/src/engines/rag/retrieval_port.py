"""检索端口（消费方契约）—— ``novamind.engines.rag`` 公共面。

批次 2 接缝：``qa`` / ``deep_research`` / ``evaluation`` 等消费方依赖 ``RetrievalPort``
抽象，而非直接 import ``SearchService``。宿主在 ``adapters/retrieval_port_adapter.py``
提供 ``HostRetrievalPort`` 实现（包 ``SearchService``）。

端口只暴露消费方实际需要的方法：``search``（含权限 + 配置 + 改写 + LLM 生成的完整检索响应）。
纯检索 ``RetrievalEngine.retrieve_raw`` 是引擎内部能力，不在此端口暴露——需要纯检索的进阶
消费方经独立端口接入。

批次 6a-3 去 schema 绑定：``search`` 入参 ``request`` 去类型化为 ``Any``，端口不再 import
宿主 ``features.knowledge_space.schemas.search_schema.SearchRequest``。消费方仍传宿主
``SearchRequest`` 对象（duck-type 透传），``HostRetrievalPort`` 直接转发给
``SearchService.search``，零转换、零下游改动。``request`` 在端口边界保持不透明（opaque
host payload），是端口与宿主 schema 解耦的刻意设计。

批次 6x 归位 ``engines/rag/``：端口与引擎同包，host 经
``from novamind.engines.rag import RetrievalPort`` 导入。
"""
from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class RetrievalPort(Protocol):
    """检索服务端口（消费方依赖此抽象，宿主提供实现）。"""

    async def search(
        self,
        space_id: int,
        kb_id: int,
        user_id: int,
        request: Any,
    ) -> Dict[str, Any]:
        """执行检索，返回完整响应 dict（results / answer / rewritten_queries 等）。

        实现负责权限校验、模式可用性、查询改写、模型客户端解析、LLM 回答生成。
        ``request`` 为宿主 ``SearchRequest``-like 对象（端口边界不透明，见模块 docstring）。
        """
        ...