"""
Deep Research 引擎端口。

仅服务本引擎的端口放本目录；跨引擎复用端口（``PromptProvider``/``WebSearchPort``）
留 ``engines/ports.py`` 与 ``engines/search_ports.py``。
"""
from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class InternalSearchPort(Protocol):
    """内部知识库检索端口：引擎经此调宿主多租户 KB 检索，切断对 ORM/setting/knowledge_space 的依赖。

    宿主装配点构造 ``HostInternalSearchPort``（绑定 space_id/user_id/config）注入引擎，
    引擎按调用查询，不持有租户上下文。

    返回归一化结果字典列表（与纯函数 ``deduplicate_results``/``format_search_context``/
    ``extract_key_sources`` 的 dict ``.get`` 访问及 feature 侧持久化一致）。
    """

    async def search(self, query: str, *, top_k: int = 10) -> List[Dict[str, Any]]:
        """执行内部 RAG 检索，返回归一化结果字典列表。"""
        ...


__all__ = ["InternalSearchPort"]