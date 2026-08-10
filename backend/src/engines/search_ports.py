"""
Web 搜索端口 WebSearchPort，定义 WebSearchResult 数据类。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol, runtime_checkable


@dataclass
class WebSearchResult:
    """联网搜索单条结果。

    ``content`` / ``score`` 为可选字段（向后兼容：resume/agent 等消费方不读它们；
    deep_research 外部路径用 ``content`` 排序/去重与上下文格式化、用 ``score`` 排序）。
    """

    title: str
    url: str
    snippet: str
    content: str = ""
    score: float = 0.0


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