"""
RAG 检索引擎，包含 RetrievalEngine / RetrievalQuery / RetrievalResult / GradeRetrier。

注：宿主检索走 features/knowledge_space 的 SearchService（消费方直收具体类，
原 RetrievalPort 协议已随 R4 去 Protocol 批次删除）。
"""
from novamind.engines.rag.grade_retrier import GradeResult, GradeRetrier
from novamind.engines.rag.retrieval_engine import (
    RetrievalEngine,
    RetrievalQuery,
    RetrievalResult,
)

__all__ = [
    "RetrievalEngine",
    "RetrievalQuery",
    "RetrievalResult",
    "GradeRetrier",
    "GradeResult",
]
