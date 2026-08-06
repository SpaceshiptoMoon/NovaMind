"""
宿主功能间搜索端口。
WebSearchPort + WebSearchResult，resume 与 agent 共用。
仅依赖 stdlib，不依赖任何 feature/setting。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol, runtime_checkable


@dataclass
class WebSearchResult:
    """联网搜索单条结果"""

    title: str
    url: str
    snippet: str


@runtime_checkable
class WebSearchPort(Protocol):
    """联网搜索端口：切断消费方对 deep_research 服务的直接依赖。

    供 agent ``web_search`` 工具与 resume 公司背景补充等消费方经依赖注入使用。
    """

    async def search(
        self, query: str, max_results: int = 5
    ) -> List[WebSearchResult]:
        """执行联网搜索，返回标题/URL/摘要列表。"""
        ...