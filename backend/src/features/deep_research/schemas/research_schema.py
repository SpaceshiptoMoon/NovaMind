"""
深度研究 Schema

定义深度研究的请求和响应 Pydantic 模型
"""

from typing import Optional, List, Dict, Any, Literal
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, model_validator
from datetime import datetime

# 从模型层导入字符串枚举（值完全一致，无需重复定义）
from novamind.features.deep_research.models.research_session import (
    ResearchMode,
    SearchSource,
    ExternalSearchProvider,
)


# ==================== 枚举类型 ====================

class ResearchStatus(str, Enum):
    """研究状态（API 层字符串枚举，与模型层 IntEnum 对应）"""
    PENDING = "pending"       # 0 - 待开始
    RUNNING = "running"       # 1 - 运行中
    COMPLETED = "completed"   # 2 - 已完成
    FAILED = "failed"         # 3 - 失败
    CANCELLED = "cancelled"   # 4 - 已取消


# ==================== 内部检索配置 ====================

class InternalSearchConfig(BaseModel):
    """
    内部知识库检索配置

    细粒度控制内部 RAG 检索行为
    """

    # ========== 知识库选择 ==========
    kb_ids: Optional[List[int]] = Field(
        default=None,
        description="指定知识库 ID 列表（为空则搜索空间下所有知识库）",
    )

    # ========== 检索模式 ==========
    search_mode: Literal[
        "content_bm25",
        "content_vector",
        "content_hybrid",
        "question_bm25",
        "question_vector",
        "question_hybrid",
        "all_bm25",
        "all_vector",
        "all_hybrid",
    ] = Field(
        default="content_hybrid",
        description="""
检索模式：{target}_{algorithm}
- content_bm25: 内容全文检索
- content_vector: 内容向量检索
- content_hybrid: 内容混合检索（默认）
- question_bm25: 问题全文检索（需启用问题生成）
- question_vector: 问题向量检索
- question_hybrid: 问题混合检索
- all_hybrid: 全字段全算法融合（最强召回）
""",
    )

    # ========== 返回数量 ==========
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="每次检索返回的结果数量",
    )

    # ========== 权重配置 ==========
    vector_weight: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="向量检索权重（hybrid 模式，0=纯 BM25，1=纯向量）",
    )
    bm25_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="BM25 检索权重（hybrid 模式）",
    )

    # ========== 过滤配置 ==========
    score_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="最低分数阈值，低于此值的结果被过滤",
    )

    # ========== Rerank 配置 ==========
    rerank_enabled: bool = Field(
        default=False,
        description="是否启用 Rerank 重排序",
    )
    rerank_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Rerank 后返回的结果数量",
    )
    rerank_model: Optional[str] = Field(
        default=None,
        description="Rerank 模型名称，为空使用用户默认",
    )

    # ========== 查询改写配置 ==========
    query_rewrite_enabled: bool = Field(
        default=False,
        description="是否启用查询改写（HyDE 或子问题拆分）",
    )
    query_rewrite_strategy: Literal["hyde", "sub_query"] = Field(
        default="hyde",
        description="查询改写策略：hyde(假设性文档嵌入)/sub_query(子问题拆分)",
    )
    sub_query_count: int = Field(
        default=3,
        ge=2,
        le=5,
        description="子问题拆分数量（strategy=sub_query 时生效）",
    )
    query_rewrite_llm_model: Optional[str] = Field(
        default=None,
        description="查询改写使用的 LLM 模型名称，为空使用用户默认",
    )

    @model_validator(mode="after")
    def validate_weights_sum(self) -> "InternalSearchConfig":
        """验证 hybrid 模式下向量/BM25 权重和为 1"""
        if self.search_mode.endswith("_hybrid"):
            total = self.vector_weight + self.bm25_weight
            if abs(total - 1.0) > 0.01:
                raise ValueError(
                    f"hybrid 模式下 vector_weight({self.vector_weight}) + "
                    f"bm25_weight({self.bm25_weight}) 应等于 1.0，当前为 {total}"
                )
        return self


# ==================== 外部搜索配置 ====================

class ExternalSearchConfig(BaseModel):
    """
    外部 Web 搜索配置

    控制外部搜索引擎的行为
    """

    # ========== 搜索服务商 ==========
    provider: ExternalSearchProvider = Field(
        default=ExternalSearchProvider.DUCKDUCKGO,
        description="外部搜索服务商：tavily/serpapi/duckduckgo（默认免费）",
    )

    # ========== 返回数量 ==========
    max_results: int = Field(
        default=10,
        ge=1,
        le=50,
        description="每次搜索返回的最大结果数量",
    )

    # ========== 搜索深度 ==========
    search_depth: Literal["basic", "advanced"] = Field(
        default="basic",
        description="搜索深度（仅 Tavily 支持）：basic(快速)/advanced(深度)",
    )

    # ========== 时间范围 ==========
    time_range: Optional[Literal["day", "week", "month", "year"]] = Field(
        default=None,
        description="时间范围过滤（可选）",
    )

    # ========== 区域设置 ==========
    region: str = Field(
        default="us-en",
        description="搜索区域/语言设置",
    )


# ==================== LLM 配置 ====================

class LLMConfig(BaseModel):
    """
    LLM 模型配置

    控制报告生成、任务分解、摘要等 LLM 调用
    """

    # ========== 模型选择 ==========
    llm_model: Optional[str] = Field(
        default=None,
        description="LLM 模型名称（如 gpt-4o），为空使用默认配置",
    )

    # ========== 生成参数 ==========
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="温度参数（创造性）",
    )
    top_p: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Top-p 采样参数",
    )
    max_tokens: int = Field(
        default=4096,
        ge=1024,
        le=16384,
        description="最大生成 Token 数",
    )


# ==================== 请求模型 ====================

class ResearchRequest(BaseModel):
    """
    研究请求

    支持细粒度配置内部检索、外部搜索、LLM 模型等
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    # ========== 必填参数 ==========
    query: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="研究查询/问题",
    )

    # ========== 研究策略 ==========
    research_mode: ResearchMode = Field(
        default=ResearchMode.STANDARD,
        description="研究模式：quick(快速)/standard(标准)/deep(深度)",
    )
    search_source: SearchSource = Field(
        default=SearchSource.HYBRID,
        description="搜索来源：internal(仅内部)/external(仅外部)/hybrid(混合)",
    )

    # ========== 内部检索配置 ==========
    internal_search: InternalSearchConfig = Field(
        default_factory=InternalSearchConfig,
        description="内部知识库检索配置",
    )

    # ========== 外部搜索配置 ==========
    external_search: ExternalSearchConfig = Field(
        default_factory=ExternalSearchConfig,
        description="外部 Web 搜索配置",
    )

    # ========== LLM 配置 ==========
    llm: LLMConfig = Field(
        default_factory=LLMConfig,
        description="LLM 模型配置",
    )


# ==================== 响应模型 ====================

class ResearchTask(BaseModel):
    """子任务定义"""
    task_id: str = Field(..., description="任务 ID")
    description: str = Field(..., description="任务描述")
    priority: int = Field(default=0, description="优先级")
    dependencies: List[str] = Field(default_factory=list, description="依赖的任务 ID")


class ResearchProgress(BaseModel):
    """研究进度"""
    status: ResearchStatus = Field(..., description="当前状态")
    current_step: str = Field(..., description="当前步骤描述")
    progress_percent: float = Field(..., ge=0.0, le=100.0, description="进度百分比")
    completed_tasks: int = Field(default=0, description="已完成任务数")
    total_tasks: int = Field(default=0, description="总任务数")
    internal_searches: int = Field(default=0, description="内部 RAG 检索次数")
    external_searches: int = Field(default=0, description="外部 Web 搜索次数")


class SearchResultItem(BaseModel):
    """单个搜索结果"""
    source_type: str = Field(..., description="来源类型：internal/external")
    content: str = Field(..., description="内容摘要")
    url: Optional[str] = Field(None, description="URL（外部搜索）")
    score: float = Field(default=0.0, description="相关性分数")
    document_id: Optional[int] = Field(None, description="文档 ID（内部搜索）")
    chunk_id: Optional[int] = Field(None, description="分块 ID（内部搜索）")
    document_name: Optional[str] = Field(None, description="文档名称")
    kb_id: Optional[int] = Field(None, description="知识库 ID（内部搜索）")
    kb_name: Optional[str] = Field(None, description="知识库名称")


class ResearchStats(BaseModel):
    """研究统计信息"""
    total_tokens: int = Field(default=0, description="总消耗 Token 数")
    elapsed_seconds: int = Field(default=0, description="总耗时（秒）")
    internal_searches: int = Field(default=0, description="内部 RAG 检索次数")
    external_searches: int = Field(default=0, description="外部 Web 检索次数")
    total_results: int = Field(default=0, description="检索结果总数")


class ResearchResponse(BaseModel):
    """研究响应（非流式）"""
    model_config = ConfigDict(from_attributes=True)

    # 基础信息
    session_id: str = Field(..., description="会话 ID")
    query: str = Field(..., description="原始查询")

    # 研究策略
    research_mode: ResearchMode = Field(..., description="研究模式")
    search_source: SearchSource = Field(..., description="搜索来源")
    external_provider: Optional[ExternalSearchProvider] = Field(None, description="外部搜索提供商")

    # 研究结果
    status: ResearchStatus = Field(..., description="研究状态")
    research_topic: Optional[str] = Field(None, description="研究主题")
    research_tasks: Optional[List[ResearchTask]] = Field(None, description="子任务列表")
    final_report: Optional[str] = Field(None, description="最终研究报告")

    # 检索结果摘要
    search_summary: Optional[Dict[str, Any]] = Field(None, description="搜索摘要信息")

    # 统计信息
    stats: Dict[str, Any] = Field(default_factory=dict, description="统计信息")

    # 时间信息
    created_at: datetime = Field(..., description="创建时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")


class ResearchListItem(BaseModel):
    """研究列表项"""
    model_config = ConfigDict(from_attributes=True)

    session_id: str = Field(..., description="会话 ID")
    query: str = Field(..., description="研究查询")
    research_topic: Optional[str] = Field(None, description="研究主题")
    status: ResearchStatus = Field(..., description="研究状态")
    research_mode: ResearchMode = Field(..., description="研究模式")
    created_at: datetime = Field(..., description="创建时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")


class ResearchListResponse(BaseModel):
    """研究列表响应"""
    items: List[ResearchListItem] = Field(..., description="研究列表")
    total: int = Field(..., description="总数")
    limit: int = Field(..., description="每页数量")
    offset: int = Field(..., description="偏移量")
