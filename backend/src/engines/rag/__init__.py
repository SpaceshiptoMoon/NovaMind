"""
RAG 检索引擎：RetrievalEngine / RetrievalQuery / RetrievalResult。

注：宿主检索走 features/knowledge_space 的 SearchService（消费方直收具体类，
原 RetrievalPort 协议已随 R4 去 Protocol 批次删除）。
QueryRewriter/GradeRetrier 已随 2026-11-15 工作台剥离移除（原消费方是 agent
检索路径；宿主查询改写走 search_service 独立实现）。
"""
from novamind.engines.rag.retrieval_engine import (
    RetrievalEngine,
    RetrievalQuery,
    RetrievalResult,
)

__all__ = [
    "RetrievalEngine",
    "RetrievalQuery",
    "RetrievalResult",
]
