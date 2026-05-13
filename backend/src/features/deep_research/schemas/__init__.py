"""
深度研究模块 - Schema 层
"""

# 字符串枚举直接从模型层重导出（值完全一致）
from src.features.deep_research.models.research_session import (
    ResearchMode,
    SearchSource,
    ExternalSearchProvider,
)

from src.features.deep_research.schemas.research_schema import (
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
