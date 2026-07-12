"""
深度研究模块 - API 层

注意：为避免循环导入，请按需导入各组件
"""

# 异常类从模块顶层导入（异常定义已迁移至 deep_research/exceptions.py）
from novamind.features.deep_research.exceptions import (
    DeepResearchError,
    ResearchNotFoundError,
    ResearchFailedError,
    InvalidResearchQueryError,
    SearchProviderNotConfiguredError,
    SearchProviderUnavailableError,
    ResearchSpaceAccessDeniedError,
    ResearchModeNotSupportedError,
    ResearchRunningError,
    ResearchAccessDeniedError,
)

__all__ = [
    # 异常类
    "DeepResearchError",
    "ResearchNotFoundError",
    "ResearchFailedError",
    "InvalidResearchQueryError",
    "SearchProviderNotConfiguredError",
    "SearchProviderUnavailableError",
    "ResearchSpaceAccessDeniedError",
    "ResearchModeNotSupportedError",
    "ResearchRunningError",
    "ResearchAccessDeniedError",
]