"""
测评模块 Schema 定义
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator

from src.features.evaluation.models.evaluation_task import EvaluationStatus


# ========== 配置 Schema ==========

class EvaluationConfig(BaseModel):
    """测评配置"""
    # 检索配置
    search_mode: str = Field(default="content_hybrid", description="检索模式")
    top_k: int = Field(default=5, ge=1, le=50, description="检索返回数量")
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="检索分数阈值")

    # 生成配置
    enable_generation: bool = Field(default=True, description="是否启用生成阶段")
    llm_model: Optional[str] = Field(default=None, description="生成回答使用的模型")
    embedding_model: Optional[str] = Field(default=None, description="Embedding 模型")

    # 检索阶段评估
    retrieval_relevance_strategy: str = Field(default="llm", description="检索相关性判断策略: llm / embedding")
    enable_mrr: bool = Field(default=True, description="是否启用 MRR 指标")
    enable_recall_at_k: bool = Field(default=False, description="是否启用 Recall@K 指标")

    # 生成阶段评估
    correctness_strategy: str = Field(default="llm", description="正确性评估策略: llm / embedding / hybrid")
    faithfulness_strategy: str = Field(default="decompose", description="忠实度评估策略: decompose / llm")
    relevance_strategy: str = Field(default="reverse_question", description="相关性评估策略: reverse_question / llm")

    # 端到端评估
    enable_context_precision: bool = Field(default=True, description="是否启用 Context Precision")
    enable_context_recall: bool = Field(default=True, description="是否启用 Context Recall")
    enable_answer_similarity: bool = Field(default=True, description="是否启用 Answer Similarity")

    # 评估维度开关
    scoring_dimensions: List[str] = Field(
        default=["correctness", "faithfulness", "relevance", "quality"],
        description="启用的评分维度",
    )


# ========== 测试集解析 Schema ==========

class TestCase(BaseModel):
    """单条测试用例"""
    question: str = Field(..., min_length=1, description="测试问题")
    expected_answer: str = Field(..., min_length=1, description="期望答案")


class TestSet(BaseModel):
    """测试集"""
    name: Optional[str] = Field(default=None, description="测试集名称")
    test_cases: List[TestCase] = Field(..., min_length=1, description="测试用例列表")


# ========== 人工评分 Schema ==========

class HumanScoreItem(BaseModel):
    """单条人工评分"""
    index: int = Field(..., ge=0, description="测试用例索引")
    score: int = Field(..., ge=1, le=10, description="人工评分（1-10）")
    comment: Optional[str] = Field(default=None, max_length=1000, description="评语")


class HumanScoreRequest(BaseModel):
    """人工评分请求"""
    scores: List[HumanScoreItem] = Field(..., min_length=1, max_length=500, description="评分列表")


# ========== 测试集响应 Schema ==========

class TestSetCreateResponse(BaseModel):
    """创建测试集响应"""
    test_set_id: int = Field(..., description="测试集 ID")
    name: str = Field(..., description="测试集名称")
    filename: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小")
    total_cases: int = Field(..., description="测试用例数量")
    message: str = Field(default="测试集已上传")


class TestSetListItem(BaseModel):
    """测试集列表项"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="测试集 ID")
    name: str = Field(..., description="测试集名称")
    filename: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小")
    total_cases: int = Field(..., description="测试用例数量")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class TestSetListResponse(BaseModel):
    """测试集列表响应"""
    items: List[TestSetListItem] = Field(..., description="测试集列表")
    total: int = Field(..., description="总数")
    skip: int = Field(..., description="跳过数")
    limit: int = Field(..., description="每页数量")


class TestSetDetailResponse(BaseModel):
    """测试集详情响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="测试集 ID")
    name: str = Field(..., description="测试集名称")
    filename: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小")
    total_cases: int = Field(..., description="测试用例数量")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class TestSetUpdateRequest(BaseModel):
    """更新测试集请求"""
    name: str = Field(..., min_length=1, max_length=200, description="测试集名称")


class TestSetCasesResponse(BaseModel):
    """测试集用例预览响应"""
    test_set_id: int = Field(..., description="测试集 ID")
    total_cases: int = Field(..., description="用例总数")
    test_cases: List[TestCase] = Field(..., description="测试用例列表")


# ========== 测评任务 Schema ==========

class TaskCreateRequest(BaseModel):
    """创建测评任务请求"""
    test_set_id: int = Field(..., gt=0, description="测试集 ID")
    name: str = Field(..., min_length=1, max_length=200, description="任务名称")
    config: Optional[EvaluationConfig] = Field(default=None, description="测评配置")


class EvaluationTaskCreateResponse(BaseModel):
    """创建测评任务响应"""
    task_id: int = Field(..., description="测评任务 ID")
    name: str = Field(..., description="任务名称")
    test_set_id: int = Field(..., description="关联测试集 ID")
    status: str = Field(..., description="任务状态")
    message: str = Field(default="测评任务已创建，等待执行")


def _status_to_str(v):
    """将 int 状态转为字符串"""
    if isinstance(v, int):
        try:
            return EvaluationStatus(v).name.lower()
        except ValueError:
            return str(v)
    return v


class EvaluationTaskListItem(BaseModel):
    """测评任务列表项"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="任务 ID")
    test_set_id: int = Field(..., description="关联测试集 ID")
    name: str = Field(..., description="任务名称")
    status: str = Field(..., description="任务状态")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    @field_validator("status", mode="before")
    @classmethod
    def convert_status(cls, v):
        return _status_to_str(v)


class EvaluationTaskListResponse(BaseModel):
    """测评任务列表响应"""
    items: List[EvaluationTaskListItem] = Field(..., description="任务列表")
    total: int = Field(..., description="总数")
    skip: int = Field(..., description="跳过数")
    limit: int = Field(..., description="每页数量")


class EvaluationTaskDetailResponse(BaseModel):
    """测评任务详情响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="任务 ID")
    test_set_id: int = Field(..., description="关联测试集 ID")
    name: str = Field(..., description="任务名称")
    status: str = Field(..., description="任务状态")
    config: Optional[Dict[str, Any]] = Field(default=None, description="测评配置")
    error_message: Optional[str] = Field(default=None, description="错误信息")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    @field_validator("status", mode="before")
    @classmethod
    def convert_status(cls, v):
        return _status_to_str(v)


class EvaluationReportResponse(BaseModel):
    """测评报告响应（汇总视图）"""
    task_id: int = Field(..., description="任务 ID")
    name: str = Field(..., description="任务名称")
    status: str = Field(..., description="任务状态")
    total_cases: int = Field(..., description="测试用例总数")
    completed_cases: int = Field(default=0, description="已完成用例数")
    summary: Optional[Dict[str, Any]] = Field(default=None, description="汇总指标")
    details: Optional[List[Dict[str, Any]]] = Field(default=None, description="逐条详情")

    @field_validator("status", mode="before")
    @classmethod
    def convert_status(cls, v):
        return _status_to_str(v)


class HumanScoreResponse(BaseModel):
    """人工评分响应"""
    updated_count: int = Field(..., description="更新的评分数量")
    message: str = Field(default="评分提交成功")


class EvaluationTaskCancelResponse(BaseModel):
    """取消任务响应"""
    task_id: int = Field(..., description="任务 ID")
    status: str = Field(..., description="任务状态")
    message: str = Field(default="任务已取消")


class EvaluationTaskProgressResponse(BaseModel):
    """任务进度响应"""
    task_id: int = Field(..., description="任务 ID")
    status: str = Field(..., description="任务状态")
    current: int = Field(default=0, description="已完成用例数")
    total: int = Field(default=0, description="总用例数")
