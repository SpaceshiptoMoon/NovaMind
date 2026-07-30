"""RAG 引擎中立异常基类（批次 6a-2 新增，批次 6b 迁入 ``novamind-engine-core``）。

历史背景：``RetrievalEngine`` 原先 import 自身 feature 的 ``api.exceptions``
（``KnowledgeSpaceError``/``EmbeddingError``/``SearchError``），这些是宿主
``BaseAPIError`` 子类、带 HTTP 状态码注册（``api/startup.py`` 注册 SearchError/EmbeddingError
→ 400）。这是引擎对宿主 feature 的导入边，批次 6 物理抽包前必须切断。

本模块提供引擎自用的**中立异常**：``RagError`` 基类 + ``EmbeddingError`` / ``SearchError``。
引擎抛出中立异常，**不依赖** ``BaseAPIError`` / ``features.*``。

宿主异常码契约保留方式（plan 6a-2「装配点捕获映射」）：宿主 ``SearchService`` 在调用
``retrieve_raw`` / ``invalidate_kb_search_cache`` 处捕获中立异常，重抛为宿主
``api.exceptions.EmbeddingError`` / ``SearchError``（BaseAPIError 子类，路由层映射 400）。
映射发生在宿主装配点，引擎零宿主依赖。

依赖方向：本模块仅依赖 stdlib ``Exception``，零宿主 feature/setting/core 边。
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