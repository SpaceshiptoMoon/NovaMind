"""
深度研究模块

基于 RAG 的深度研究功能，支持：
- 内部知识库检索（RAG）
- 外部 Web 搜索（Tavily/SerpAPI/DuckDuckGo）
- 混合检索策略
- 流式/非流式响应
"""

# 数据模型
from novamind.features.deep_research.models import (
    ResearchSession,
    ResearchStatus,
)

# Schema（包含枚举定义）
from novamind.features.deep_research.schemas import (
    ResearchMode,
    SearchSource,
    ExternalSearchProvider,
    ResearchRequest,
    ResearchTask,
    ResearchProgress,
    SearchResultItem,
    ResearchStats,
    ResearchResponse,
    ResearchListItem,
    ResearchListResponse,
)

# 服务层
from novamind.features.deep_research.services import (
    ExternalSearchService,
    ExternalSearchResult,
    TavilySearchService,
    SerpAPISearchService,
    DuckDuckGoSearchService,
    DeepResearchService,
)

# 仓储层
from novamind.features.deep_research.repository import ResearchRepository

# API 层 - 使用延迟导入避免循环依赖
# 请直接从以下路径导入：
#   - router: from novamind.features.deep_research.api.routes import router
#   - dependencies: from novamind.features.deep_research.api.dependencies import ...
#   - exceptions: from novamind.features.deep_research.exceptions import ...

__all__ = [
    # 模型
    "ResearchSession",
    "ResearchStatus",
    # Schema（包含枚举）
    "ResearchMode",
    "SearchSource",
    "ExternalSearchProvider",
    "ResearchRequest",
    "ResearchTask",
    "ResearchProgress",
    "SearchResultItem",
    "ResearchStats",
    "ResearchResponse",
    "ResearchListItem",
    "ResearchListResponse",
    # 服务层
    "ExternalSearchService",
    "ExternalSearchResult",
    "TavilySearchService",
    "SerpAPISearchService",
    "DuckDuckGoSearchService",
    "DeepResearchService",
    # 仓储层
    "ResearchRepository",
]
