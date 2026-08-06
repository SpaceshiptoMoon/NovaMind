"""
知识库测评模块

提供 RAG 评估功能，支持：
- 测试集管理（上传、解析、预览）
- 测评任务管理（创建、执行、取消、进度）
- 多维度评估（检索评估、生成评估、端到端评估）
- 人工评分
- 结果导出（JSON/CSV）
"""

# 数据模型
from novamind.features.evaluation.models import (
    EvaluationTestSet,
    EvaluationTask,
    EvaluationStatus,
)

# 仓储层
from novamind.features.evaluation.repository import (
    EvaluationTestSetRepository,
    EvaluationTaskRepository,
)

# Schema
from novamind.features.evaluation.schemas import (
    EvaluationConfig,
    TestCase,
    TestSet,
    HumanScoreItem,
    HumanScoreRequest,
    EvaluationTaskCreateResponse,
    EvaluationTaskListItem,
    EvaluationTaskListResponse,
    EvaluationTaskDetailResponse,
    EvaluationReportResponse,
    HumanScoreResponse,
    TestSetCreateResponse,
    TestSetListItem,
    TestSetListResponse,
    TestSetDetailResponse,
    TestSetUpdateRequest,
    TestSetCasesResponse,
    TaskCreateRequest,
    EvaluationTaskCancelResponse,
    EvaluationTaskProgressResponse,
)

# 服务层 - 使用延迟导入避免循环依赖
# 请直接从以下路径导入：
#   - EvaluationService: from novamind.features.evaluation.services.evaluation_service import EvaluationService
#   - RetrievalEvaluator: from novamind.engines.eval.retrieval_evaluator import RetrievalEvaluator
#   - GenerationEvaluator: from novamind.engines.eval.generation_evaluator import GenerationEvaluator
#   - EmbeddingEvaluator: from novamind.engines.eval.embedding_evaluator import EmbeddingEvaluator
#   - ClaimDecomposer: from novamind.engines.eval.claim_decomposer import ClaimDecomposer

# API 层 - 使用延迟导入避免循环依赖
# 请直接从以下路径导入：
#   - router: from novamind.features.evaluation.api.routes import router
#   - dependencies: from novamind.features.evaluation.api.dependencies import ...
#   - exceptions: from novamind.features.evaluation.exceptions import ...

__all__ = [
    # 模型
    "EvaluationTestSet",
    "EvaluationTask",
    "EvaluationStatus",
    # 仓储层
    "EvaluationTestSetRepository",
    "EvaluationTaskRepository",
    # Schema
    "EvaluationConfig",
    "TestCase",
    "TestSet",
    "HumanScoreItem",
    "HumanScoreRequest",
    "EvaluationTaskCreateResponse",
    "EvaluationTaskListItem",
    "EvaluationTaskListResponse",
    "EvaluationTaskDetailResponse",
    "EvaluationReportResponse",
    "HumanScoreResponse",
    "TestSetCreateResponse",
    "TestSetListItem",
    "TestSetListResponse",
    "TestSetDetailResponse",
    "TestSetUpdateRequest",
    "TestSetCasesResponse",
    "TaskCreateRequest",
    "EvaluationTaskCancelResponse",
    "EvaluationTaskProgressResponse",
]
