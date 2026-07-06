"""
知识库 Schema

定义知识库的请求和响应模型

字段命名与数据库模型 (KnowledgeBase) 保持一致:
- space_id: 所属空间ID
- name: 知识库名称
- creator_id: 创建者ID
- config: 知识库配置 (JSON)
- storage: 存储配置 (JSON)
- stats: 统计信息 (JSON)
- status: 状态 (SmallInteger: 0-已删除, 1-活跃, 2-已归档)
"""

from typing import Optional, List, Literal, Dict, Any, Annotated, Union
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_serializer, field_validator, Tag

from src.features.knowledge_space.models.knowledge_base import KnowledgeBaseStatus


# ========== 切分策略配置 ==========


class RecursiveSplittingConfig(BaseModel):
    """递归字符切分策略"""
    model_config = ConfigDict(extra="ignore")

    strategy: Literal["recursive"] = "recursive"
    chunk_size: int = Field(default=1000, ge=50, le=4000, description="目标分块大小，字符数")
    chunk_overlap: int = Field(default=100, ge=0, le=500, description="相邻分块重叠字符数")
    min_chunk_size: int = Field(default=500, ge=0, le=2000, description="最小分块大小，小于此值的碎块与相邻块合并（0=不合并）")


class FixedSizeSplittingConfig(BaseModel):
    """固定大小切分策略"""
    model_config = ConfigDict(extra="ignore")

    strategy: Literal["fixed_size"] = "fixed_size"
    chunk_size: int = Field(default=1000, ge=50, le=4000, description="目标分块大小，字符数")
    chunk_overlap: int = Field(default=100, ge=0, le=500, description="相邻分块重叠字符数")


class MarkdownSplittingConfig(BaseModel):
    """Markdown 结构切分策略"""
    model_config = ConfigDict(extra="ignore")

    strategy: Literal["markdown"] = "markdown"
    max_chunk_size: int = Field(default=2000, ge=100, le=8000, description="最大分块大小")
    min_chunk_size: int = Field(default=100, ge=10, le=1000, description="最小分块大小")


class SemanticSplittingConfig(BaseModel):
    """语义切分策略"""
    model_config = ConfigDict(extra="ignore")

    strategy: Literal["semantic"] = "semantic"
    max_chunk_size: int = Field(default=2000, ge=100, le=8000, description="最大分块大小")
    similarity_threshold: float = Field(
        default=0.7, ge=0.0, le=1.0,
        description="语义相似度阈值，低于此值则切分",
    )
    batch_size: int = Field(
        default=20, ge=1, le=100,
        description="语义切分批处理大小",
    )


SplittingConfig = Annotated[
    Union[
        Annotated[RecursiveSplittingConfig, Tag("recursive")],
        Annotated[FixedSizeSplittingConfig, Tag("fixed_size")],
        Annotated[MarkdownSplittingConfig, Tag("markdown")],
        Annotated[SemanticSplittingConfig, Tag("semantic")],
    ],
    Field(discriminator="strategy"),
]


# ========== 解析配置 ==========


class ParsingConfig(BaseModel):
    """文档解析配置"""
    extract_images: bool = Field(default=False, description="是否提取图片")
    extract_tables: bool = Field(default=True, description="是否提取表格")
    ocr_enabled: bool = Field(default=False, description="是否启用 OCR")
    preserve_structure: bool = Field(default=True, description="是否保留文档结构")
    encoding: str = Field(default="utf-8", description="文件编码")
    vlm_description_enabled: bool = Field(
        default=False,
        description="是否启用 VLM 图片描述（多模态空间），开启后上传图片时调用视觉模型生成文本描述，支持 BM25 + 文本向量检索",
    )
    # 视频解析配置（全模态空间）
    video: Optional["VideoParsingConfig"] = Field(
        default=None,
        description="视频文件解析配置（空间包含 video 模态时有效）",
    )
    # 音频解析配置（全模态空间）
    audio: Optional["AudioParsingConfig"] = Field(
        default=None,
        description="音频文件解析配置（空间包含 audio 模态时有效）",
    )


class VideoParsingConfig(BaseModel):
    """视频文件解析配置"""
    frame_interval: float = Field(
        default=5.0, ge=1.0, le=60.0,
        description="关键帧提取间隔（秒），默认每5秒一帧",
    )
    max_frames: int = Field(
        default=60, ge=1, le=200,
        description="最多提取帧数，默认60帧",
    )


class AudioParsingConfig(BaseModel):
    """音频文件解析配置"""
    asr_model: str = Field(
        default="whisper-1",
        description="ASR 转写模型名称，默认 whisper-1",
    )
    chunk_split_strategy: Literal["sentence", "fixed"] = Field(
        default="sentence",
        description="切分策略: sentence(按句子)/fixed(按固定字符数)",
    )
    chunk_size: int = Field(
        default=1000, ge=100, le=4000,
        description="固定大小切分的字符数（仅 chunk_split_strategy=fixed 时有效）",
    )


# ========== 问题生成 LLM 配置 ==========


class QuestionLLMConfig(BaseModel):
    """问题生成使用的 LLM 配置

    用于生成假设性问题（HyDE），可独立于检索时的 LLM 配置。
    """
    model: Optional[str] = Field(
        default=None,
        description="LLM 模型名称，为空使用用户默认"
    )
    temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="生成温度（0-2，问题生成建议 0.3 以确保格式稳定）"
    )
    top_p: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="核采样参数（0-1，越高越多样）"
    )
    max_tokens: int = Field(
        default=2048,
        ge=100,
        le=8192,
        description="最大生成 token 数"
    )


# ========== 问题生成配置 ==========


# 默认问题生成提示词模板（使用单花括号，与 PromptManager.format_prompt 兼容）
DEFAULT_QUESTION_PROMPT = """请严格根据以下文档内容，生成 {count} 个用户可能会问的问题。

要求：
1. 问题必须且只能基于下方「文档内容」中实际出现的文字信息，禁止使用文档内容之外的人名、地名、机构名等实体
2. 问题应该覆盖文档的核心信息点
3. 问题应该是用户真实可能提出的查询
4. 问题表述要清晰、简洁
5. 只输出 JSON 数组，不要输出任何其他文字、标记或解释

输出格式：
[{{"question": "问题内容", "category": "factual"}}]

category 可选值: factual(事实性), conceptual(概念性), procedural(操作性)

文档内容：
{content}

请生成 {count} 个问题："""


class QuestionGenerationConfig(BaseModel):
    """假设问题生成配置

    启用后，系统会在文档切分时为每个分块生成假设性问题，
    这些问题会与分块内容一起被向量化，用于问题检索模式。
    """
    enabled: bool = Field(default=False, description="是否启用假设问题生成")
    llm: Optional[QuestionLLMConfig] = Field(
        default=None,
        description="LLM 配置（为空则使用全局默认配置）"
    )
    max_questions_per_chunk: int = Field(
        default=5,
        ge=1,
        le=20,
        description="每个分块生成的最大问题数"
    )
    prompt_template: Optional[str] = Field(
        default=None,
        max_length=4000,
        description="""自定义提示词模板（可选）
支持的变量：
- {{content}}: 分块内容
- {{count}}: 生成问题数量

为空则使用默认模板。示例：
请根据以下内容生成 {{count}} 个问题：
{{content}}

问题列表："""
    )


# ========== 知识库完整配置 ==========


class KnowledgeBaseConfig(BaseModel):
    """知识库完整配置（创建时使用）

    注意：检索策略不存数据库，由前端在调用检索接口时作为请求参数传入。
    此配置仅管理离线阶段（切分/解析/问题生成）。
    Embedding 模型由空间级别统一管理，知识库运行时自动读取空间配置，不存储副本。
    """
    space_type: List[str] = Field(
        default_factory=lambda: ["text"],
        description="知识库支持的数据模态: text/image/video/audio",
    )

    @field_validator("space_type", mode="before")
    @classmethod
    def normalize_space_type(cls, v):
        """兼容旧格式: 'text' → ['text'], 'multimodal' → ['image']"""
        if isinstance(v, str):
            if v == "multimodal":
                return ["image"]
            return [v]
        if isinstance(v, list):
            return v
        return ["text"]

    description: str = Field(default="", max_length=2000, description="知识库描述")
    splitting: SplittingConfig = Field(default_factory=RecursiveSplittingConfig, description="切分配置")
    parsing: ParsingConfig = Field(default_factory=ParsingConfig, description="解析配置")
    question_generation: QuestionGenerationConfig = Field(
        default_factory=QuestionGenerationConfig,
        description="假设问题生成配置",
    )


# ========== 创建/更新 Schema ==========


class KnowledgeBaseCreate(BaseModel):
    """创建知识库请求"""
    name: str = Field(..., min_length=1, max_length=100, description="知识库名称")
    config: Optional[KnowledgeBaseConfig] = Field(None, description="知识库配置（不传则使用默认值）")


class KnowledgeBaseUpdate(BaseModel):
    """更新知识库请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="知识库名称")
    config: Optional[KnowledgeBaseConfig] = Field(None, description="知识库配置")


class KnowledgeBaseResponse(BaseModel):
    """知识库响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="知识库ID")
    space_id: int = Field(..., description="所属空间ID")
    name: str = Field(..., description="知识库名称")
    creator_id: int = Field(..., description="创建者ID")
    config: Optional[Dict[str, Any]] = Field(None, description="知识库配置")
    storage: Optional[Dict[str, Any]] = Field(None, description="存储配置")
    status: int = Field(default=1, description="状态: 0-已删除, 1-活跃, 2-已归档")
    stats: Optional[Dict[str, Any]] = Field(None, description="统计信息")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    @field_serializer('status')
    def serialize_status(self, value) -> int:
        """序列化状态枚举为整数"""
        if hasattr(value, 'value'):
            return value.value
        return int(value) if value is not None else 1


class KnowledgeBaseListResponse(BaseModel):
    """知识库列表响应"""
    items: List[KnowledgeBaseResponse] = Field(..., description="知识库列表")
    total: int = Field(..., description="总数")
    skip: int = Field(..., description="跳过数量")
    limit: int = Field(..., description="返回数量")


# ========== 配置管理相关 Schema ==========


class KnowledgeBaseConfigUpdate(BaseModel):
    """知识库配置部分更新请求（只传要改的字段，深度合并）

    注意：召回策略不存数据库，由前端在调用召回接口时作为请求参数传入。
    此接口仅管理离线阶段配置（splitting / parsing / question_generation）。
    Embedding 模型由空间级别统一管理，不可通过知识库配置修改。
    """
    space_type: Optional[List[str]] = Field(None, description="知识库支持的数据模态: text/image/video/audio")
    splitting: Optional[SplittingConfig] = Field(None, description="切分配置")
    parsing: Optional[ParsingConfig] = Field(None, description="解析配置")
    question_generation: Optional[QuestionGenerationConfig] = Field(None, description="问题生成配置")


class KnowledgeBaseConfigResponse(BaseModel):
    """知识库配置查询响应"""
    kb_id: int = Field(..., description="知识库ID")
    name: str = Field(..., description="知识库名称")
    config: KnowledgeBaseConfig = Field(..., description="完整配置")
    stats: Dict[str, Any] = Field(..., description="统计信息")
