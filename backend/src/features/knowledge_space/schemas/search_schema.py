"""
检索 Schema

定义检索的请求和响应模型
"""

from typing import Optional, List, Dict, Any, Literal
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, model_validator


class SearchMode(str, Enum):
    """
    统一检索模式（文本空间）

    格式: {target}_{algorithm}
    - content_bm25: 内容全文检索
    - content_vector: 内容向量检索
    - content_hybrid: 内容混合检索
    - question_bm25: 问题全文检索
    - question_vector: 问题向量检索
    - question_hybrid: 问题混合检索
    - all_bm25: 全字段全文检索
    - all_vector: 全字段向量检索
    - all_hybrid: 全字段全算法融合
    """
    CONTENT_BM25 = "content_bm25"
    CONTENT_VECTOR = "content_vector"
    CONTENT_HYBRID = "content_hybrid"
    QUESTION_BM25 = "question_bm25"
    QUESTION_VECTOR = "question_vector"
    QUESTION_HYBRID = "question_hybrid"
    ALL_BM25 = "all_bm25"
    ALL_VECTOR = "all_vector"
    ALL_HYBRID = "all_hybrid"


class QueryRewriteConfig(BaseModel):
    """
    查询改写配置

    支持两种改写策略：
    - hyde: 假设性文档嵌入（HyDE），先用 LLM 生成假设性答案，
            再用答案的 embedding 检索，缩小查询与文档的语义鸿沟
    - sub_query: 子问题拆分，将复杂查询拆解为多个子问题，
            分别检索后合并，提高多维度信息的召回覆盖率
    """

    # 改写策略
    strategy: Literal["hyde", "sub_query"] = Field(
        default="hyde",
        description="查询改写策略：hyde(假设性文档嵌入)/sub_query(子问题拆分)",
    )

    # 子问题拆分参数
    sub_query_count: int = Field(
        default=3,
        ge=2,
        le=5,
        description="子问题拆分数量",
    )
    sub_query_merge_mode: Literal["rrf", "score"] = Field(
        default="rrf",
        description="子问题结果合并方式：rrf(加权融合)/score(分数取最大)",
    )

    # 查询改写使用的 LLM 模型
    llm_model: Optional[str] = Field(
        default=None,
        description="查询改写使用的 LLM 模型名称，为空使用用户默认",
    )


class WeightConfig(BaseModel):
    """
    检索权重配置

    控制混合检索中各路信号的影响力分配。
    - hybrid 模式：vector_weight / bm25_weight 控制算法偏好
    - all_* 模式：content_weight / question_weight 控制字段偏好
    - all_hybrid 模式：四路权重通过乘法组合
    """

    # 算法权重（hybrid 模式）
    vector_weight: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="向量检索权重（0=纯BM25，1=纯向量）"
    )
    bm25_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="BM25 检索权重"
    )

    # 字段权重（all_* 模式）
    content_weight: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="内容字段权重（全字段检索时有效）"
    )
    question_weight: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="问题字段权重（全字段检索时有效）"
    )

    # RRF 平滑参数
    rrf_k: int = Field(
        default=60,
        ge=1,
        description="RRF 平滑参数（k 越大排名差异越平滑）"
    )


class RerankConfig(BaseModel):
    """
    Rerank 重排序配置

    对检索结果进行二次精排序，提升 Top-K 的精准度。
    """

    enabled: bool = Field(
        default=False,
        description="是否启用 Rerank 重排序",
    )
    top_k: int = Field(
        default=3,
        ge=1,
        description="Rerank 后返回的结果数量",
    )
    model: Optional[str] = Field(
        default=None,
        description="Rerank 模型名称，为空使用用户默认",
    )


class LLMConfig(BaseModel):
    """
    LLM 回答配置

    对召回结果生成 LLM 回答。
    """

    enabled: bool = Field(
        default=False,
        description="是否启用 LLM 回答",
    )
    model: Optional[str] = Field(
        default=None,
        description="LLM 模型名称，为空使用用户默认",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="生成温度（0-2，越高越随机）",
    )
    top_p: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="核采样参数（0-1，越高越多样）",
    )


class SearchRequest(BaseModel):
    """
    统一检索请求

    支持多种检索策略和检索目标的灵活组合。

    组合示例：
    - content_hybrid: 内容混合检索（默认）
    - all_hybrid: 全字段全算法融合（最强召回）
    - question_hybrid: 问题混合检索（需启用问题生成）
    """

    # 必填参数
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="查询文本",
        examples=["如何使用 FastAPI 构建 REST API"]
    )

    # 统一检索模式
    search_mode: SearchMode = Field(
        default=SearchMode.CONTENT_HYBRID,
        description="""
统一检索模式：{target}_{algorithm}
- content_bm25: 内容全文检索
- content_vector: 内容向量检索
- content_hybrid: 内容混合检索（默认）
- question_bm25: 问题全文检索（需启用问题生成）
- question_vector: 问题向量检索（需启用问题生成）
- question_hybrid: 问题混合检索（需启用问题生成）
- all_bm25: 全字段全文检索（需启用问题生成）
- all_vector: 全字段向量检索（需启用问题生成）
- all_hybrid: 全字段全算法融合（需启用问题生成，最强召回）
"""
    )

    # 返回数量
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="返回结果数量"
    )

    # 嵌套配置
    weights: Optional[WeightConfig] = Field(
        default=None,
        description="检索权重配置（为空使用默认权重）",
    )
    rerank: Optional[RerankConfig] = Field(
        default=None,
        description="Rerank 重排序配置（为空则不重排序）",
    )
    llm: Optional[LLMConfig] = Field(
        default=None,
        description="LLM 回答配置（为空则不生成回答）",
    )
    query_rewrite: Optional[QueryRewriteConfig] = Field(
        default=None,
        description="查询改写配置（为空则不改写）",
    )

    # 后过滤
    score_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="最低分数阈值，低于此值的结果被过滤",
    )

    # 降级控制
    fallback_on_unavailable: bool = Field(
        default=True,
        description="检索模式不可用时是否自动降级"
    )

    # 是否使用缓存
    use_cache: bool = Field(
        default=True,
        description="是否使用检索缓存"
    )


class MultimodalSearchMode(str, Enum):
    """多模态检索子模式"""
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_IMAGE = "image_to_image"


class MultimodalSearchRequest(BaseModel):
    """
    多模态检索请求

    统一处理以文搜图和以图搜图两种模式
    """
    # 查询内容：文本或图片（根据模式二选一）
    query: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=2000,
        description="文本查询（以文搜图模式必填）",
    )
    image_base64: Optional[str] = Field(
        default=None,
        description="Base64 编码的图片数据（以图搜图模式必填）",
    )

    # 检索模式
    search_mode: MultimodalSearchMode = Field(
        default=MultimodalSearchMode.TEXT_TO_IMAGE,
        description="检索模式: text_to_image 或 image_to_image",
    )

    # 结果参数
    top_k: int = Field(default=10, ge=1, le=100, description="返回结果数量")
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="相似度阈值（归一化后）")

    @model_validator(mode="after")
    def validate_query_or_image(self):
        """根据模式校验必填字段"""
        if self.search_mode == MultimodalSearchMode.TEXT_TO_IMAGE and not self.query:
            raise ValueError("text_to_image 模式需要提供 query")
        if self.search_mode == MultimodalSearchMode.IMAGE_TO_IMAGE and not self.image_base64:
            raise ValueError("image_to_image 模式需要提供 image_base64")
        return self


class SearchResult(BaseModel):
    """检索结果项"""

    model_config = ConfigDict(from_attributes=True)

    # 关联信息
    chunk_id: str = Field(..., description="分块 ID")
    document_id: int = Field(..., description="文档 ID")
    kb_id: int = Field(..., description="知识库 ID")

    # 内容
    content: str = Field(..., description="检索到的内容")

    # 分数
    score: float = Field(..., description="融合分数")

    # 索引
    chunk_index: Optional[int] = Field(None, description="分块索引")

    # 问题信息（question_*/all_* 模式下有值）
    questions: Optional[List[str]] = Field(None, description="该分块预生成的假设性问题列表")

    # 元数据
    metadata: Optional[Dict[str, Any]] = Field(None, description="分块元数据")
    file_info: Optional[Dict[str, Any]] = Field(None, description="文件信息")

    # 媒体文件
    image_url: Optional[str] = Field(None, description="图片预览 URL（已废弃，请使用 media_url）")
    media_url: Optional[str] = Field(None, description="媒体文件预览 URL（图片/视频/音频）")
    chunk_type: Optional[str] = Field(None, description="分块类型: text/image/video/audio")


class SearchResponse(BaseModel):
    """检索响应"""

    model_config = ConfigDict(from_attributes=True)

    # 结果列表
    results: List[SearchResult] = Field(..., description="检索结果列表")

    # 统计信息
    total: int = Field(..., description="结果总数")
    query: str = Field(..., description="原始查询文本")

    # 检索参数
    search_mode: str = Field(..., description="实际使用的检索模式")
    original_mode: Optional[str] = Field(None, description="原始请求的检索模式（发生降级时有值）")
    mode_fallback: bool = Field(default=False, description="是否发生了模式降级")
    top_k: int = Field(..., description="请求的返回数量")
    vector_weight: Optional[float] = Field(None, description="向量检索权重")
    bm25_weight: Optional[float] = Field(None, description="BM25 检索权重")

    # LLM 回答（当 llm.enabled=true 时返回）
    answer: Optional[str] = Field(None, description="LLM 生成的回答（启用 LLM 时返回）")
    answer_model: Optional[str] = Field(None, description="生成回答使用的模型名称")
    answer_elapsed_ms: Optional[float] = Field(None, description="LLM 回答耗时（毫秒）")

    # 性能指标
    elapsed_ms: Optional[float] = Field(None, description="检索耗时（毫秒）")
    cached: bool = Field(default=False, description="结果是否来自缓存")

    # 查询改写信息（启用 query_rewrite 时返回）
    rewritten_queries: Optional[List[str]] = Field(
        None,
        description="查询改写后的问题列表（sub_query 时为子问题，hyde 时为假设性文档）",
    )


class SearchModeItem(BaseModel):
    """单个检索模式描述"""
    mode: str = Field(..., description="检索模式标识")
    label: str = Field(..., description="检索模式显示名称")
    description: str = Field(..., description="检索模式描述")
    requires_question_generation: bool = Field(..., description="是否需要启用问题生成")


class SearchModesResponse(BaseModel):
    """可用检索模式列表响应"""
    model_config = ConfigDict(from_attributes=True)
    modes: List[SearchModeItem] = Field(..., description="可用检索模式列表")
    total: int = Field(..., description="可用模式总数")


# 检索模式定义
SEARCH_MODES: List[Dict[str, Any]] = [
    # 内容模式
    {"mode": "content_bm25", "label": "内容全文检索", "description": "使用 BM25 算法对内容进行全文检索", "requires_question_generation": False},
    {"mode": "content_vector", "label": "内容向量检索", "description": "使用向量相似度对内容进行语义检索", "requires_question_generation": False},
    {"mode": "content_hybrid", "label": "内容混合检索", "description": "结合 BM25 和向量检索的内容混合检索", "requires_question_generation": False},
    # 问题模式
    {"mode": "question_bm25", "label": "问题全文检索", "description": "使用 BM25 算法对假设问题进行全文检索", "requires_question_generation": True},
    {"mode": "question_vector", "label": "问题向量检索", "description": "使用向量相似度对假设问题进行语义检索", "requires_question_generation": True},
    {"mode": "question_hybrid", "label": "问题混合检索", "description": "结合 BM25 和向量检索的问题混合检索", "requires_question_generation": True},
    # 全字段模式
    {"mode": "all_bm25", "label": "全字段全文检索", "description": "对内容和问题同时进行 BM25 检索", "requires_question_generation": True},
    {"mode": "all_vector", "label": "全字段向量检索", "description": "对内容和问题同时进行向量检索", "requires_question_generation": True},
    {"mode": "all_hybrid", "label": "全字段全算法融合", "description": "对所有字段同时使用 BM25 和向量检索，并通过 RRF 融合", "requires_question_generation": True},
    # 多模态模式（仅多模态空间可用）
    {"mode": "image_vector", "label": "以图搜图", "description": "使用图片向量搜索相似图片", "requires_question_generation": False},
    {"mode": "text_to_image", "label": "以文搜图", "description": "使用文本向量搜索相关图片", "requires_question_generation": False},
]

# 模式降级映射
SEARCH_MODE_FALLBACK = {
    "question_bm25": "content_bm25",
    "question_vector": "content_vector",
    "question_hybrid": "content_hybrid",
    "all_bm25": "content_bm25",
    "all_vector": "content_vector",
    "all_hybrid": "content_hybrid",
}


# ========== 知识库模型配置 ==========

class KnowledgeBaseModelConfigResponse(BaseModel):
    """知识库模型配置响应"""

    model_config = ConfigDict(from_attributes=True)

    # Embedding 模型配置
    embedding_model: Optional[str] = Field(
        None,
        description="知识库使用的 Embedding 模型名称"
    )
    embedding_dimension: Optional[int] = Field(
        None,
        description="Embedding 向量维度"
    )

    # 默认 LLM 模型（全局配置）
    default_llm_model: Optional[str] = Field(
        None,
        description="默认 LLM 模型名称（用于查询改写等）"
    )

    # 默认 Rerank 模型（全局配置）
    default_rerank_model: Optional[str] = Field(
        None,
        description="默认 Rerank 模型名称"
    )

    # 可用模型列表
    available_embedding_models: List[str] = Field(
        default_factory=list,
        description="用户可用的 Embedding 模型列表"
    )
    available_llm_models: List[str] = Field(
        default_factory=list,
        description="用户可用的 LLM 模型列表"
    )
    available_rerank_models: List[str] = Field(
        default_factory=list,
        description="用户可用的 Rerank 模型列表"
    )
