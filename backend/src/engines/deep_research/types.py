"""
Deep Research 引擎核心数据类型。

承载可复用研究机制的纯数据契约：检索来源枚举、引擎研究参数、归一化检索结果、
搜索事件流变体。本模块不得 import ``novamind.features.*`` / ``novamind.setting.*`` /
ORM 模型 / ``core.database``（分层铁律：engines 是纯逻辑层）。

- ``SearchSource``：检索来源枚举（internal/external/hybrid）。此前定义在 ORM 模型
  ``features/deep_research/models/research_session.py``，但它是引擎决策
  （``should_use_external_search``）依赖的纯枚举，不接 ORM，故迁入引擎层；
  feature 侧 ORM 模型 / schemas / repository 经 re-export 反向引用（feature -> engine 合法）。
- ``EngineResearchParams``：纯 dataclass 研究参数，**无 Any / feature DTO**，引擎无状态
  方法按调用接收。
- ``ResearchResultItem``：归一化检索结果（内部/外部两路统一形状），与 feature 侧
  Pydantic ``SearchResultItem`` 分离（避命名冲突）。
- ``SearchEvent`` 变体：``DeepResearchEngine.search`` 产出的异步事件流，host 消费后持久化。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum as PyEnum
from typing import Any, Dict, List, Optional, Union


class SearchSource(str, PyEnum):
    """检索来源枚举"""

    INTERNAL = "internal"      # 内部知识库
    EXTERNAL = "external"       # 外部网络搜索
    HYBRID = "hybrid"           # 混合检索


@dataclass
class EngineResearchParams:
    """引擎研究参数（纯 dataclass，host 从 feature ``ResearchRequest`` 装配后注入）。

    **不含 Any / feature DTO**：所有字段为原始类型，确保引擎无状态方法可复用。
    """

    search_source: SearchSource
    depth: int
    iterations: int
    top_k: int
    external_max_results: int
    llm_max_tokens: int
    llm_temperature: float
    llm_top_p: float
    llm_model: Optional[str] = None


@dataclass
class ResearchResultItem:
    """归一化检索结果（内部 RAG 与外部 Web 两路统一形状）。

    与 feature 侧 Pydantic ``SearchResultItem``（API 响应 DTO）分离，避免命名冲突。
    外部结果填 ``url``/``title``/``snippet``/``content``/``score``；
    内部结果额外填 ``document_id``/``chunk_id``/``document_name``/``kb_id``/``kb_name``。
    """

    title: str = ""
    url: str = ""
    snippet: str = ""
    content: str = ""
    score: float = 0.0
    source: str = ""  # "internal" / "external"
    document_id: Optional[int] = None
    chunk_id: Optional[int] = None
    document_name: Optional[str] = None
    kb_id: Optional[int] = None
    kb_name: Optional[str] = None


@dataclass
class TaskStarted:
    """单个研究任务开始事件。"""

    task_id: str
    description: str
    total_iterations: int


@dataclass
class IterationProgress:
    """单次迭代进度事件。"""

    task_id: str
    iteration: int
    use_external: bool
    step_count: int
    total_steps: int
    current_results_count: int


@dataclass
class TaskFailed:
    """单任务检索失败事件（catch-and-continue，不中断整个研究）。"""

    task_id: str
    error: str


@dataclass
class SearchComplete:
    """全部任务检索完成事件，携带归一化结果与摘要。"""

    all_results: List[ResearchResultItem]
    summary: Dict[str, Any] = field(default_factory=dict)


SearchEvent = Union[TaskStarted, IterationProgress, TaskFailed, SearchComplete]


__all__ = [
    "SearchSource",
    "EngineResearchParams",
    "ResearchResultItem",
    "TaskStarted",
    "IterationProgress",
    "TaskFailed",
    "SearchComplete",
    "SearchEvent",
]