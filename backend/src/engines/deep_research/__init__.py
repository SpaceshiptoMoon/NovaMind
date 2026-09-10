"""
Deep Research 引擎包：可复用的深度研究机制（查询分析/计划规划/迭代检索/综合报告）。

与 ``engines/rag`` / ``engines/agent`` / ``engines/resume`` 同级，属 engines 纯逻辑层。
业务编排（ORM/setting/多租户/SSE/持久化）留 ``features/deep_research/``。

- ``types``：纯数据契约（SearchSource/StepType/PlanStep/ResearchPlan/EngineResearchParams/SearchEvent）
- ``ports``：本引擎端口（InternalSearchPort）；跨引擎端口在 ``engines/ports.py`` / ``engines/search_ports.py``
- ``errors``：引擎级异常（feature 边界映射为 feature 异常）
- ``engine``：``DeepResearchEngine`` 无状态方法（analyze_query/analyze_plan/background_investigation/
  search/synthesize_report[_stream]）+ 纯模块函数
"""
from novamind.engines.deep_research.types import (
    EngineResearchParams,
    IterationProgress,
    PlanStep,
    ResearchPlan,
    SearchComplete,
    SearchEvent,
    SearchSource,
    StepType,
    TaskFailed,
    TaskStarted,
)
from novamind.engines.deep_research.errors import EngineInvalidResearchQueryError
from novamind.engines.deep_research.ports import InternalSearchPort
from novamind.engines.deep_research.engine import (
    KEY_ANALYZE_QUERY,
    KEY_DECOMPOSE_TASKS,
    KEY_GENERATE_QUERY,
    KEY_PLAN,
    KEY_PROCESSING_STEP,
    KEY_SYNTHESIZE_REPORT,
    KEY_SYNTHESIZE_REPORT_STREAM,
    KEY_TASK_FINDING,
    SUFFICIENT_RESULT_COUNT,
    MAX_ITERATION_THRESHOLD,
    DeepResearchEngine,
    deduplicate_results,
    extract_key_sources,
    format_search_context,
    is_sufficient_results,
    parse_plan,
    should_use_external_search,
)

__all__ = [
    # 类型
    "SearchSource",
    "StepType",
    "PlanStep",
    "ResearchPlan",
    "EngineResearchParams",
    "SearchEvent",
    "TaskStarted",
    "IterationProgress",
    "TaskFailed",
    "SearchComplete",
    # 端口
    "InternalSearchPort",
    # 引擎类
    "DeepResearchEngine",
    # 错误
    "EngineInvalidResearchQueryError",
    # 常量
    "SUFFICIENT_RESULT_COUNT",
    "MAX_ITERATION_THRESHOLD",
    "KEY_ANALYZE_QUERY",
    "KEY_DECOMPOSE_TASKS",
    "KEY_PLAN",
    "KEY_PROCESSING_STEP",
    "KEY_SYNTHESIZE_REPORT",
    "KEY_SYNTHESIZE_REPORT_STREAM",
    "KEY_GENERATE_QUERY",
    "KEY_TASK_FINDING",
    # 纯函数
    "should_use_external_search",
    "is_sufficient_results",
    "deduplicate_results",
    "extract_key_sources",
    "format_search_context",
    "parse_plan",
]
