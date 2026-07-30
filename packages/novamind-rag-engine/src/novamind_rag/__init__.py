"""NovaMind RAG 检索引擎——纯检索段可嵌入独立库。

公开面：

- ``RetrievalEngine``：纯检索引擎（缓存读写 + 向量生成 + ES 检索 + 归一化 + 阈值过滤 + rerank）
- ``RetrievalQuery``：纯检索入参 dataclass（宿主从 SearchRequest + 改写结果构造注入）
- ``RetrievalResult``：``retrieve_raw`` 返回值（仅含结果列表 + 是否命中缓存）
- ``RetrievalPort``：检索服务端口 Protocol（消费方依赖此抽象，宿主提供实现）

引擎不做权限校验、不碰 ORM、不调 LLM、不感知 ``ModelConfigService``。客户端由宿主通过
resolver 回调按需注入。
"""

from novamind_rag.retrieval_engine import RetrievalEngine, RetrievalQuery, RetrievalResult
from novamind_rag.retrieval_port import RetrievalPort

__all__ = [
    "RetrievalEngine",
    "RetrievalQuery",
    "RetrievalResult",
    "RetrievalPort",
]
