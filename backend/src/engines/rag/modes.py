"""检索模式枚举（SearchMode）——检索查询契约的中立位。

引擎（engines/agent 工具、engines/rag）与业务 schema 共用同一枚举；
定义在此避免 engines→features 反向 import。业务 schema（features/
knowledge_space/schemas/search_schema.py）re-export 保持既有引用兼容。
"""
from __future__ import annotations

from enum import Enum


class SearchMode(str, Enum):
    """
    统一检索模式（文本空间）

    格式: {target}_{algorithm}
    - content_bm25: 内容全文检索
    - content_vector: 内容向量检索
    - content_hybrid: 内容混合检索
    - question_bm25: 问题全文检索
    - question_vector: 问题向量检索
    - question_hybrid: 问题混合检索
    - all_bm25: 全字段全文检索
    - all_vector: 全字段向量检索
    - all_hybrid: 全字段全算法融合
    """
    CONTENT_BM25 = "content_bm25"
    CONTENT_VECTOR = "content_vector"
    CONTENT_HYBRID = "content_hybrid"
    QUESTION_BM25 = "question_bm25"
    QUESTION_VECTOR = "question_vector"
    QUESTION_HYBRID = "question_hybrid"
    ALL_BM25 = "all_bm25"
    ALL_VECTOR = "all_vector"
    ALL_HYBRID = "all_hybrid"
