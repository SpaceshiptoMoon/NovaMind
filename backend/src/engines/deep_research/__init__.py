"""
Deep Research 引擎包：可复用的深度研究机制（查询分析/任务分解/迭代检索/综合报告）。

与 ``engines/rag`` / ``engines/agent`` / ``engines/resume`` 同级，属 engines 纯逻辑层。
业务编排（ORM/setting/多租户/SSE/持久化）留 ``features/deep_research/``。

- ``types``：纯数据契约（SearchSource/EngineResearchParams/ResearchResultItem/SearchEvent）
- ``ports``：本引擎端口（InternalSearchPort）；跨引擎端口在 ``engines/ports.py`` / ``engines/search_ports.py``
- ``errors``：引擎级异常（feature 边界映射为 feature 异常）
- ``engine``：``DeepResearchEngine`` 无状态方法（A-2/A-3 完成类组装）+ 纯模块函数
"""
from novamind.engines.deep_research.types import (
    EngineResearchParams,
    IterationProgress,
    ResearchResultItem,
    SearchComplete,
    SearchEvent,
    SearchSource,
    TaskFailed,
    TaskStarted,
)
from novamind.engines.deep_research.errors import EngineInvalidResearchQueryError
from novamind.engines.deep_research.ports import InternalSearchPort
from novamind.engines.deep_research.engine import (
    KEY_ANALYZE_QUERY,
    KEY_DECOMPOSE_TASKS,
    KEY_SYNTHESIZE_REPORT,
    KEY_SYNTHESIZE_REPORT_STREAM,
    SUFFICIENT_RESULT_COUNT,
    MAX_ITERATION_THRESHOLD,
    deduplicate_results,
    extract_key_sources,
    format_search_context,
    is_sufficient_results,
    should_use_external_search,
)

__all__ = [
    # 类型
    "SearchSource",
    "EngineResearchParams",
    "ResearchResultItem",
    "SearchEvent",
    "TaskStarted",
    "IterationProgress",
    "TaskFailed",
    "SearchComplete",
    # 端口
    "InternalSearchPort",
    # 错误
    "EngineInvalidResearchQueryError",
    # 常量
    "SUFFICIENT_RESULT_COUNT",
    "MAX_ITERATION_THRESHOLD",
    "KEY_ANALYZE_QUERY",
    "KEY_DECOMPOSE_TASKS",
    "KEY_SYNTHESIZE_REPORT",
    "KEY_SYNTHESIZE_REPORT_STREAM",
    # 纯函数
    "should_use_external_search",
    "is_sufficient_results",
    "deduplicate_results",
    "extract_key_sources",
    "format_search_context",
]