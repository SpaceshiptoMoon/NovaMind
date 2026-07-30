"""RAG 检索引擎——纯检索能力，通过端口从宿主注入依赖。

公共面：
  - ``RetrievalEngine`` — 纯检索引擎（``retrieve_raw``）
  - ``RetrievalQuery`` — 检索请求中立体（17 字段 slots dataclass）
  - ``RetrievalResult`` — 检索结果（results + cached）
  - ``RetrievalPort`` — 检索服务端口（消费方依赖此抽象）
"""
from novamind.engines.rag.retrieval_engine import (
    RetrievalEngine,
    RetrievalQuery,
    RetrievalResult,
)
from novamind.engines.rag.retrieval_port import RetrievalPort

__all__ = [
    "RetrievalEngine",
    "RetrievalQuery",
    "RetrievalResult",
    "RetrievalPort",
]
