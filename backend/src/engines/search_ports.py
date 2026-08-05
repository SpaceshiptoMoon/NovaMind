"""宿主功能间搜索端口（与 ``engines/ports.py`` 同层，非引擎端口）。

``WebSearchPort`` + ``WebSearchResult`` 原位于 ``features/agent/core/ports.py``（批次 3）。
批次 5 resume 引擎端口化需要消费同一端口，若 resume 直接 import
``agent.core.ports`` 会形成 resume -> agent 的 feature 导入边，破坏批次 6 将
``novamind-resume-engine`` 抽成独立包（resume_engine 仅依赖 LLMProvider+PromptProvider
+ 搜索端口）。故将搜索端口提升到中立 ``engines/search_ports.py``，
``agent/core/ports.py`` 改为 re-export（批次 3 代码与测试零改动）。

设计约束与 ``engines/ports.py``、``shared/registry_ports.py`` 一致：
  - 协议只描述能力，不携带 ORM/枚举/配置键等业务实体。
  - 依赖方向：各 feature / 引擎 -> 本协议；本协议 ✗-> 任何 feature/setting。
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