"""
RAG 检索引擎，包含 RetrievalEngine / RetrievalQuery / RetrievalResult / GradeRetrier。

注：``RetrievalPort``（消费方检索契约）已迁至 ``novamind.shared.retrieval_port``——
消费方全在 features 层，属 feature 间公共契约，归 shared 中立位置。
"""
from novamind.engines.rag.retrieval_engine import (
    RetrievalEngine,
    RetrievalQuery,
    RetrievalResult,
)
from novamind.engines.rag.grade_retrier import GradeRetrier, GradeResult

__all__ = [
    "RetrievalEngine",
    "RetrievalQuery",
    "RetrievalResult",
    "GradeRetrier",
    "GradeResult",
]
