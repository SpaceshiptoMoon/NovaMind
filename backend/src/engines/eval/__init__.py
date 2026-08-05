"""测评引擎——RAG 检索/生成质量评估的纯逻辑组件。

零 ``features`` / ``setting`` / ORM 依赖；LLM、Embedding、Prompt、Logger 均经端口
或 ``shared.ai_models`` 注入。由 ``features/evaluation`` 装配点实例化并编排。

组件：
  embedding_evaluator   基于 Embedding 的余弦相似度评估
  claim_decomposer      LLM Claim 拆解 + 忠实度验证
  generation_evaluator  生成质量评估（LLM-as-Judge / 反向问题 / hybrid）
  retrieval_evaluator   检索质量评估（Precision@K / Hit Rate / MRR / Context Recall）
"""
from novamind.engines.eval.embedding_evaluator import EmbeddingEvaluator
from novamind.engines.eval.claim_decomposer import ClaimDecomposer
from novamind.engines.eval.generation_evaluator import GenerationEvaluator
from novamind.engines.eval.retrieval_evaluator import RetrievalEvaluator

__all__ = [
    "EmbeddingEvaluator",
    "ClaimDecomposer",
    "GenerationEvaluator",
    "RetrievalEvaluator",
]