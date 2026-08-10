"""
Deep Research 引擎级异常。

引擎内部抛出，feature 边界（``deep_research_service``）映射为 feature 异常
``InvalidResearchQueryError``，保留具体信息。
"""


class EngineInvalidResearchQueryError(Exception):
    """引擎级研究查询无效错误（如 sanitize 后内容为空/过短）。"""

    pass


__all__ = ["EngineInvalidResearchQueryError"]