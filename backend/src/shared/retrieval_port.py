"""
检索端口（消费方契约）。
RetrievalPort 提供 search 方法，消费方依赖此抽象；宿主在 adapter 提供
HostRetrievalPort（包 SearchService）。
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