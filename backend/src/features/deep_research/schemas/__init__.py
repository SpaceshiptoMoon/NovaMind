"""
深度研究模块 - Schema 层
"""

# 字符串枚举：ResearchMode/ExternalSearchProvider 从模型层重导出；
# SearchSource 自 engines/deep_research/types 反向 re-export（feature -> engine 合法）。
from novamind.features.deep_research.models.research_session import (
    ResearchMode,
    ExternalSearchProvider,
)
from novamind.engines.deep_research.types import SearchSource

from novamind.features.deep_research.schemas.research_schema import (
    # 枚举（仅 ResearchStatus 需要在 Schema 层单独定义，因为 API 用字符串而 DB 用整数）
    ResearchStatus,
    # 请求
    ResearchRequest,
    # 响应
    ResearchTask,
    ResearchProgress,
    SearchResultItem,
    ResearchStats,
    ResearchResponse,
    ResearchListItem,
    ResearchListResponse,
)

__all__ = [
    # 枚举
    "ResearchMode",
    "SearchSource",
    "ExternalSearchProvider",
    "ResearchStatus",
    # 请求
    "ResearchRequest",
    # 响应
    "ResearchTask",
    "ResearchProgress",
    "SearchResultItem",
    "ResearchStats",
    "ResearchResponse",
    "ResearchListItem",
    "ResearchListResponse",
]
