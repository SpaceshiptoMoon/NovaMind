"""
RAG 引擎中立异常基类。
RagError / EmbeddingError / SearchError，仅依赖 stdlib Exception，
不依赖宿主 BaseAPIError。
"""
from __future__ import annotations

__all__ = ["RagError", "EmbeddingError", "SearchError"]


class RagError(Exception):
    """RAG 引擎中立异常基类。

    引擎内部一切预期错误继承此类。宿主装配点捕获后映射为对应宿主 BaseAPIError。
    """


class EmbeddingError(RagError):
    """Embedding 生成/配置相关错误（中立）。"""


class SearchError(RagError):
    """检索执行/缓存失效相关错误（中立）。"""