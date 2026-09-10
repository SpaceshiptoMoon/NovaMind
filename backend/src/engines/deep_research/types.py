"""
Deep Research 引擎核心数据类型。

承载可复用研究机制的纯数据契约：检索来源枚举、引擎研究参数、搜索事件流变体。
本模块不得 import ``novamind.features.*`` / ``novamind.setting.*`` /
ORM 模型 / ``core.database``（分层铁律：engines 是纯逻辑层）。

- ``SearchSource``：检索来源枚举（internal/external/hybrid）。此前定义在 ORM 模型
  ``features/deep_research/models/research_session.py``，但它是引擎决策
  （``should_use_external_search``）依赖的纯枚举，不接 ORM，故迁入引擎层；
  feature 侧 ORM 模型 / schemas / repository 经 re-export 反向引用（feature -> engine 合法）。
- ``EngineResearchParams``：纯 dataclass 研究参数，**无 Any / feature DTO**，引擎无状态
  方法按调用接收。
- ``SearchEvent`` 变体：``DeepResearchEngine.search`` 产出的异步事件流，host 消费后持久化。
  ``SearchComplete.all_results`` 为 ``List[Dict[str, Any]]``（归一化检索结果字典），
  与纯函数 ``deduplicate_results`` / ``format_search_context`` / ``extract_key_sources``
  （dict ``.get`` 访问）及 feature 侧持久化（repo 存 dict、synthesize_report 自持久化
  dict 经 format_search_context 派生上下文）一致——全程统一用 dict，避免反复转换
  （R1：忠实复现原非流语义，最低风险）。
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


class StepType(str, PyEnum):
    """研究步骤类型（deer-flow 对齐）。

    - RESEARCH：检索型步骤（调检索端口迭代收集信息）
    - PROCESSING：纯分析步骤（不调检索，LLM 综合前序发现产出结论；
      对应 deer-flow 的 processing/analyst 步骤语义）
    """

    RESEARCH = "research"
    PROCESSING = "processing"


@dataclass
class PlanStep:
    """研究计划单步骤（deer-flow Step 对齐）。

    ``execution_res`` 为执行后回填的结果（research 路径为该步骤的 finding
    摘要；processing 路径为 LLM 分析结论），持久化时截 1000 字符。
    """

    step_id: str
    title: str
    description: str
    step_type: StepType = StepType.RESEARCH
    need_search: bool = True
    execution_res: str = ""


@dataclass
class ResearchPlan:
    """研究计划（deer-flow Plan 对齐）。

    - ``has_enough_context``：planner 看到 background 调查结果后的 Context
      Assessment 判定——true 时 steps 可为空，管线跳过检索直接 reporter。
    - ``locale``：仅形状对齐 deer-flow，NovaMind 不填（报告语言跟 query 走）。
    - ``iteration``：规划轮次（0=首轮；EDIT_PLAN 重规划 +1）。
    """

    title: str = ""
    thought: str = ""
    has_enough_context: bool = False
    locale: str = ""
    steps: List["PlanStep"] = field(default_factory=list)
    iteration: int = 0
    background_investigation_results: List[Dict[str, Any]] = field(default_factory=list)


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
class TaskStarted:
    """单个研究任务开始事件。"""

    task_id: str
    description: str
    total_iterations: int


@dataclass
class IterationProgress:
    """单次迭代进度事件。

    ``current_query`` 为本轮实际使用的检索 query：固定 query 模式（无 LLM）下等于
    任务描述；观察驱动模式（deer-flow 对齐）下是 LLM 基于已有观察演化出的新 query。
    """

    task_id: str
    iteration: int
    use_external: bool
    step_count: int
    total_steps: int
    current_results_count: int
    current_query: str = ""


@dataclass
class TaskFailed:
    """单任务检索失败事件（catch-and-continue，不中断整个研究）。"""

    task_id: str
    error: str


@dataclass
class TaskFinding:
    """单任务完成后的 finding 摘要事件（deer-flow 对齐）。

    LLM 将该任务检索结果压缩为一段要点+结论式摘要，注入后续任务的 query 生成
    prompt（跨任务信息流：后执行任务知道前面已查明什么，避免重复检索）。
    host 可选择忽略该事件（不影响现有消费方）。
    """

    task_id: str
    finding: str


@dataclass
class SearchComplete:
    """全部任务检索完成事件，携带归一化结果与摘要。

    ``all_results`` 为归一化检索结果字典列表（内部/外部两路统一形状），
    feature 侧据此持久化与综合报告。``summary`` 含 internal_count/external_count/
    total_results/key_sources。``task_findings`` 为各任务 finding 摘要累积
    （[{task_id, finding}]，deer-flow observations 的对应物，喂 reporter 提升
    报告 grounding）。
    """

    all_results: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    task_findings: List[Dict[str, str]] = field(default_factory=list)


SearchEvent = Union[TaskStarted, IterationProgress, TaskFailed, TaskFinding, SearchComplete]


__all__ = [
    "SearchSource",
    "StepType",
    "PlanStep",
    "ResearchPlan",
    "EngineResearchParams",
    "TaskStarted",
    "IterationProgress",
    "TaskFailed",
    "TaskFinding",
    "SearchComplete",
    "SearchEvent",
]