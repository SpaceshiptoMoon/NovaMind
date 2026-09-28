"""知识库测评模块：测试集管理（上传/解析/预览）、测评任务异步执行与取消、多维度评估（检索/生成/端到端）、人工评分与结果导出。"""

# 数据模型
from novamind.features.evaluation.models import (
    EvaluationStatus,
    EvaluationTask,
    EvaluationTestSet,
)

# 仓储层
from novamind.features.evaluation.repository import (
    EvaluationTaskRepository,
    EvaluationTestSetRepository,
)

# Schema
from novamind.features.evaluation.schemas import (
    EvaluationConfig,
    EvaluationReportResponse,
    EvaluationTaskCancelResponse,
    EvaluationTaskCreateResponse,
    EvaluationTaskDetailResponse,
    EvaluationTaskListItem,
    EvaluationTaskListResponse,
    EvaluationTaskProgressResponse,
    HumanScoreItem,
    HumanScoreRequest,
    HumanScoreResponse,
    TaskCreateRequest,
    TestCase,
    TestSet,
    TestSetCasesResponse,
    TestSetCreateResponse,
    TestSetDetailResponse,
    TestSetListItem,
    TestSetListResponse,
    TestSetUpdateRequest,
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
