"""
深度研究模块异常定义（兼容层）

异常类已迁移到模块顶层 src/features/deep_research/exceptions.py，
此处仅做重新导出以保持向后兼容。
新代码请直接从 src.features.deep_research.exceptions 导入。
"""

from src.features.deep_research.exceptions import (  # noqa: F401
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
