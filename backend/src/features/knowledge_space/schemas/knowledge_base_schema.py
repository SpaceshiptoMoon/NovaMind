"""
Knowledge base schemas.

This module defines the request/response models for knowledge-base config and
provides the new parsing config structure with backward-compatible migration
from the legacy flat parsing layout.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


# ========== Shared default constants ==========
# Single source of truth for splitting defaults — all consumers should reference these
# instead of hardcoding their own values.

DEFAULT_CHUNK_STRATEGY = "recursive"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_MIN_CHUNK_SIZE = 500
DEFAULT_MAX_CHUNK_SIZE = 2000
DEFAULT_SIMILARITY_THRESHOLD = 0.7
DEFAULT_BATCH_SIZE = 20
DEFAULT_EMBEDDING_BATCH_SIZE = 32


# ========== Splitting config ==========


# Legacy splitting-strategy names that predate the current Literal set. KB configs
# persisted under older schema versions may still carry these values; we normalize
# them on read so stale DB rows don't fail Pydantic validation. Mirrors the
# migrate_legacy_parsing approach used for ParsingConfig.
LEGACY_SPLITTING_STRATEGY_ALIASES: Dict[str, str] = {
    "sentence": "recursive",  # legacy audio transcript strategy
    "fixed": "fixed_size",    # legacy video description strategy
}


def _migrate_legacy_splitting_strategy(value: Any) -> Any:
    """Normalize legacy splitting strategy names to the current Literal set.

    Applied to the top-level strategy and to the nested audio/video overrides.
    Unknown values are left untouched so they still surface a clear validation
    error rather than being silently coerced to a wrong strategy.
    """
    if not isinstance(value, dict):
        return value

    normalized = dict(value)
    top_strategy = normalized.get("strategy")
    if isinstance(top_strategy, str):
        normalized["strategy"] = LEGACY_SPLITTING_STRATEGY_ALIASES.get(
            top_strategy, top_strategy
        )

    for sub_key in ("audio", "video"):
        sub_cfg = normalized.get(sub_key)
        if isinstance(sub_cfg, dict) and isinstance(sub_cfg.get("strategy"), str):
            sub_cfg = dict(sub_cfg)
            sub_cfg["strategy"] = LEGACY_SPLITTING_STRATEGY_ALIASES.get(
                sub_cfg["strategy"], sub_cfg["strategy"]
            )
            normalized[sub_key] = sub_cfg

    return normalized


class AudioChunkOverride(BaseModel):
    """Audio-specific chunk override.

    Strategy must match a registered splitter name in DocumentRegistry.
    Currently registered: recursive, fixed_size, markdown, semantic.
    "recursive" is recommended for audio transcripts (respects sentence boundaries).
    """

    model_config = ConfigDict(extra="ignore")

    strategy: Literal["recursive", "fixed_size", "markdown", "semantic"] = Field(
        default="recursive",
        description="Chunking strategy for audio transcripts.",
    )
    chunk_size: int = Field(
        default=1000,
        ge=100,
        le=4000,
        description="Chunk size used when strategy=fixed_size or recursive.",
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_strategy(cls, value):
        return _migrate_legacy_splitting_strategy(value)


class VideoChunkOverride(BaseModel):
    """Video-specific chunk override.

    Strategy must match a registered splitter name in DocumentRegistry.
    "fixed_size" groups consecutive frame descriptions up to chunk_size.
    """

    model_config = ConfigDict(extra="ignore")

    strategy: Literal["recursive", "fixed_size", "markdown", "semantic"] = Field(
        default="fixed_size",
        description="Chunking strategy for video descriptions.",
    )
    chunk_size: int = Field(
        default=1500,
        ge=100,
        le=4000,
        description="Maximum merged description length.",
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_strategy(cls, value):
        return _migrate_legacy_splitting_strategy(value)


class SplittingConfig(BaseModel):
    """Common splitting config."""

    model_config = ConfigDict(extra="ignore")

    strategy: Literal["recursive", "fixed_size", "markdown", "semantic"] = Field(
        default=DEFAULT_CHUNK_STRATEGY,
        description="Default splitting strategy.",
    )
    chunk_size: int = Field(default=DEFAULT_CHUNK_SIZE, ge=50, le=4000)
    chunk_overlap: int = Field(default=DEFAULT_CHUNK_OVERLAP, ge=0, le=500)
    min_chunk_size: int = Field(default=DEFAULT_MIN_CHUNK_SIZE, ge=0, le=2000)
    max_chunk_size: int = Field(default=DEFAULT_MAX_CHUNK_SIZE, ge=100, le=8000)
    similarity_threshold: float = Field(default=DEFAULT_SIMILARITY_THRESHOLD, ge=0.0, le=1.0)
    batch_size: int = Field(default=DEFAULT_BATCH_SIZE, ge=1, le=100)
    audio: Optional[AudioChunkOverride] = Field(default=None)
    video: Optional[VideoChunkOverride] = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_strategy(cls, value):
        return _migrate_legacy_splitting_strategy(value)


# ========== Parsing config ==========


PdfParserName = Literal[
    "layout",
    "plain",
    "vision",
    "docling",
    "mineru",
    "opendataloader",
    "paddleocr",
    "somark",
    "tcadp",
]

LegacyDeepDocParserId = Literal[
    "pdf_layout",
    "pdf_plain",
    "pdf_vision",
    "pdf_docling",
    "pdf_mineru",
    "pdf_opendataloader",
    "pdf_paddleocr",
    "pdf_somark",
    "pdf_tcadp",
    "docx",
    "epub",
    "excel",
    "ppt",
    "figure",
    "text",
    "txt",
    "markdown",
    "html",
    "json",
]


class TextTypeParsingConfig(BaseModel):
    """Per-document-type text parsing config."""

    model_config = ConfigDict(extra="ignore")

    strategy: Literal["default", "deepdoc"] = Field(default="default")


class PdfParsingConfig(TextTypeParsingConfig):
    """PDF parsing config."""

    parser: Optional[PdfParserName] = Field(default=None)
    ocr_enabled: bool = Field(default=False)

    @model_validator(mode="after")
    def validate_parser_usage(self):
        if self.strategy == "default" and self.parser is not None:
            raise ValueError("pdf.strategy=default forbids parser")
        return self


class TextParsingConfig(BaseModel):
    """Text parsing config grouped by document type."""

    model_config = ConfigDict(extra="ignore")

    pdf: PdfParsingConfig = Field(default_factory=PdfParsingConfig)
    docx: TextTypeParsingConfig = Field(default_factory=TextTypeParsingConfig)
    excel: TextTypeParsingConfig = Field(default_factory=TextTypeParsingConfig)
    ppt: TextTypeParsingConfig = Field(default_factory=TextTypeParsingConfig)
    epub: TextTypeParsingConfig = Field(default_factory=TextTypeParsingConfig)
    markdown: TextTypeParsingConfig = Field(default_factory=TextTypeParsingConfig)
    html: TextTypeParsingConfig = Field(default_factory=TextTypeParsingConfig)
    txt: TextTypeParsingConfig = Field(default_factory=TextTypeParsingConfig)
    json_file: TextTypeParsingConfig = Field(
        default_factory=TextTypeParsingConfig,
        alias="json",
        serialization_alias="json",
    )


class ImageParsingConfig(BaseModel):
    """Image parsing config.

    strategy:
    - "vlm": 使用 VLM 生成图片描述文本，再走文本 Embedding 索引（需要 VLM 模型）
    - "deepdoc_ocr": 使用 DeepDoc OCR 提取图片文字，再走文本 Embedding 索引（无需 VLM）
    """

    model_config = ConfigDict(extra="ignore")

    strategy: Literal["vlm", "deepdoc_ocr"] = Field(
        default="vlm",
        description="图片解析策略：vlm(VLM描述)/deepdoc_ocr(DeepDoc OCR文字提取)",
    )
    vlm_model: Optional[str] = Field(
        default=None,
        description="VLM 模型名称（strategy=vlm 时可选，留空使用用户默认 VLM 模型）",
    )


class VideoParsingConfig(BaseModel):
    """Video parsing config."""

    model_config = ConfigDict(extra="ignore")

    frame_interval: float = Field(default=5.0, ge=1.0, le=60.0)
    max_frames: int = Field(default=60, ge=1, le=200)
    vlm_description_enabled: bool = Field(default=False)
    vlm_model: Optional[str] = Field(default=None)
    # VLM 主模型因配额/鉴权类错误失败时，回退到的备用 VLM 模型名（用户在模型管理中配置过的）。
    vlm_fallback_model: Optional[str] = Field(default=None)
    # 当所有帧的 VLM 描述均因配额/鉴权类错误失败时，是否跳过 VLM 并写一条占位描述，
    # 而不是让整个文档任务失败。默认 False（fail fast，抛业务异常提示用户）。
    vlm_skip_on_quota_error: bool = Field(default=False)


class AudioParsingConfig(BaseModel):
    """Audio parsing config."""

    model_config = ConfigDict(extra="ignore")

    asr_model: str = Field(default="whisper-1")
    language: Optional[str] = Field(default=None)


class ParsingConfig(BaseModel):
    """Top-level parsing config."""

    model_config = ConfigDict(extra="ignore")

    strategy: Optional[Literal["default", "deepdoc"]] = Field(default=None)
    deepdoc_parser_id: Optional[LegacyDeepDocParserId] = Field(default=None)
    deepdoc_pdf_mode: Optional[Literal["layout", "plain", "vision"]] = Field(default=None)
    text: Optional[TextParsingConfig] = Field(default=None)
    image: Optional[ImageParsingConfig] = Field(default=None)
    video: Optional[VideoParsingConfig] = Field(default=None)
    audio: Optional[AudioParsingConfig] = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_parsing(cls, value):
        if not isinstance(value, dict):
            return value

        # 迁移旧 image.strategy="ocr" → "deepdoc_ocr"
        image_cfg = value.get("image")
        if isinstance(image_cfg, dict) and image_cfg.get("strategy") == "ocr":
            image_cfg = dict(image_cfg)
            image_cfg["strategy"] = "deepdoc_ocr"
            value = dict(value)
            value["image"] = image_cfg

        legacy_keys = {
            "strategy",
            "deepdoc_parser_id",
            "deepdoc_pdf_mode",
            "ocr_enabled",
            "vlm_description_enabled",
            "vlm_model",
        }
        if not any(key in value for key in legacy_keys):
            return value

        legacy = dict(value)
        strategy = str(legacy.get("strategy", "default"))
        parser_id = legacy.get("deepdoc_parser_id")
        pdf_mode = legacy.get("deepdoc_pdf_mode")
        ocr_enabled = bool(legacy.get("ocr_enabled", False))
        vlm_enabled = bool(legacy.get("vlm_description_enabled", False))
        vlm_model = legacy.get("vlm_model")

        migrated: Dict[str, Any] = {
            "strategy": strategy,
            "deepdoc_parser_id": parser_id,
            "deepdoc_pdf_mode": pdf_mode if pdf_mode in {"layout", "plain", "vision"} else None,
            "text": {
                "pdf": {"strategy": "default", "ocr_enabled": ocr_enabled},
                "docx": {"strategy": "default"},
                "excel": {"strategy": "default"},
                "ppt": {"strategy": "default"},
                "epub": {"strategy": "default"},
                "markdown": {"strategy": "default"},
                "html": {"strategy": "default"},
                "txt": {"strategy": "default"},
                "json_file": {"strategy": "default"},
            },
            "video": legacy.get("video"),
            "audio": legacy.get("audio"),
        }

        parser_to_type: Dict[str, tuple[str, Optional[str]]] = {
            "pdf_layout": ("pdf", "layout"),
            "pdf_plain": ("pdf", "plain"),
            "pdf_vision": ("pdf", "vision"),
            "pdf_docling": ("pdf", "docling"),
            "pdf_mineru": ("pdf", "mineru"),
            "pdf_opendataloader": ("pdf", "opendataloader"),
            "pdf_paddleocr": ("pdf", "paddleocr"),
            "pdf_somark": ("pdf", "somark"),
            "pdf_tcadp": ("pdf", "tcadp"),
            "docx": ("docx", None),
            "epub": ("epub", None),
            "excel": ("excel", None),
            "ppt": ("ppt", None),
            "markdown": ("markdown", None),
            "html": ("html", None),
            "txt": ("txt", None),
            "json": ("json_file", None),
            "text": ("txt", None),
        }
        if parser_id in parser_to_type:
            doc_type, parser_name = parser_to_type[parser_id]
            migrated["text"][doc_type]["strategy"] = "deepdoc"
            if parser_name is not None:
                migrated["text"]["pdf"]["parser"] = parser_name
        elif strategy == "deepdoc":
            migrated["text"]["pdf"]["strategy"] = "deepdoc"

        if vlm_enabled or vlm_model:
            migrated["image"] = {
                "strategy": "vlm",
                "vlm_model": vlm_model,
            }
        # 旧 ocr 策略迁移为 deepdoc_ocr
        elif isinstance(value.get("image"), dict) and value["image"].get("strategy") == "ocr":
            migrated["image"] = {"strategy": "deepdoc_ocr"}

        merged = dict(migrated)
        for key, current_value in value.items():
            if key == "text" and isinstance(current_value, dict):
                merged_text = dict(migrated["text"])
                for doc_type, doc_config in current_value.items():
                    merged_text[doc_type] = doc_config
                merged["text"] = merged_text
                continue
            if key == "image" and current_value is not None:
                merged["image"] = current_value
                continue
            if key == "video" and current_value is not None:
                merged["video"] = current_value
                continue
            if key == "audio" and current_value is not None:
                merged["audio"] = current_value
                continue
            merged[key] = current_value

        return merged


# ========== Question generation ==========


class QuestionLLMConfig(BaseModel):
    """Question-generation LLM config."""

    model: Optional[str] = Field(default=None)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    max_tokens: int = Field(default=2048, ge=100, le=8192)


class QuestionGenerationConfig(BaseModel):
    """Question-generation config."""

    enabled: bool = Field(default=False)
    llm: Optional[QuestionLLMConfig] = Field(default=None)
    max_questions_per_chunk: int = Field(default=5, ge=1, le=20)
    prompt_template: Optional[str] = Field(default=None, max_length=4000)


# ========== Full KB config ==========


class KnowledgeBaseConfig(BaseModel):
    """Full knowledge-base config."""

    space_type: List[Literal["text", "image", "video", "audio"]] = Field(
        default_factory=lambda: ["text"],
        description="数据模态列表：text=文本文档, image=图片, video=视频, audio=音频",
    )
    description: str = Field(default="", max_length=2000)
    splitting: SplittingConfig = Field(default_factory=SplittingConfig)
    parsing: ParsingConfig = Field(default_factory=ParsingConfig)
    question_generation: QuestionGenerationConfig = Field(default_factory=QuestionGenerationConfig)


# ========== Request / response schemas ==========


class KnowledgeBaseCreate(BaseModel):
    """Create KB request."""

    name: str = Field(..., min_length=1, max_length=100)
    config: Optional[KnowledgeBaseConfig] = Field(default=None)


class KnowledgeBaseUpdate(BaseModel):
    """Update KB request."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    config: Optional[KnowledgeBaseConfig] = Field(default=None)


class KnowledgeBaseResponse(BaseModel):
    """Knowledge-base response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    space_id: int
    name: str
    creator_id: int
    config: Optional[Dict[str, Any]] = None
    storage: Optional[Dict[str, Any]] = None
    status: int = 1
    stats: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("status")
    def serialize_status(self, value) -> int:
        if hasattr(value, "value"):
            return value.value
        return int(value) if value is not None else 1


class KnowledgeBaseListResponse(BaseModel):
    """Knowledge-base list response."""

    items: List[KnowledgeBaseResponse]
    total: int
    skip: int
    limit: int


class KnowledgeBaseConfigUpdate(BaseModel):
    """Partial config update request."""

    space_type: Optional[List[Literal["text", "image", "video", "audio"]]] = Field(
        default=None,
        description="数据模态列表：text=文本文档, image=图片, video=视频, audio=音频",
    )
    splitting: Optional[SplittingConfig] = Field(default=None)
    parsing: Optional[ParsingConfig] = Field(default=None)
    question_generation: Optional[QuestionGenerationConfig] = Field(default=None)


class KnowledgeBaseConfigResponse(BaseModel):
    """Knowledge-base config response."""

    model_config = ConfigDict(from_attributes=True)

    kb_id: int
    name: str
    config: KnowledgeBaseConfig
    stats: Dict[str, Any]


PDF_PARSER_TO_LEGACY_ID: Dict[str, str] = {
    "layout": "pdf_layout",
    "plain": "pdf_plain",
    "vision": "pdf_vision",
    "docling": "pdf_docling",
    "mineru": "pdf_mineru",
    "opendataloader": "pdf_opendataloader",
    "paddleocr": "pdf_paddleocr",
    "somark": "pdf_somark",
    "tcadp": "pdf_tcadp",
}


TEXT_DOC_TYPES = ("pdf", "docx", "excel", "ppt", "epub", "markdown", "html", "txt", "json")


def build_runtime_parsing_config(parsing: Optional[Dict[str, Any]], file_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Convert the new nested parsing config into the legacy runtime parsing shape.

    Runtime parsers still expect legacy keys such as:
    - strategy
    - deepdoc_parser_id
    - deepdoc_pdf_mode
    - ocr_enabled
    - vlm_description_enabled
    - vlm_model
    """
    parsed = ParsingConfig.model_validate(parsing or {})
    result: Dict[str, Any] = {}
    if parsed.strategy is not None:
        result["strategy"] = parsed.strategy
    if parsed.deepdoc_parser_id is not None:
        result["deepdoc_parser_id"] = parsed.deepdoc_parser_id
    if parsed.deepdoc_pdf_mode is not None:
        result["deepdoc_pdf_mode"] = parsed.deepdoc_pdf_mode

    normalized_file_type = (file_type or "").lower()
    text = parsed.text or TextParsingConfig()

    if not file_type:
        if parsed.deepdoc_parser_id is not None:
            return result
        if parsed.deepdoc_pdf_mode is not None:
            result.setdefault("deepdoc_pdf_mode", parsed.deepdoc_pdf_mode)
            return result

    target_doc_type = normalized_file_type
    inferred_non_pdf_deepdoc: str | None = None
    if not target_doc_type:
        for doc_type in ("docx", "excel", "ppt", "epub", "markdown", "html", "txt", "json"):
            attr_name = "json_file" if doc_type == "json" else doc_type
            cfg = getattr(text, attr_name, None)
            if cfg and cfg.strategy == "deepdoc":
                inferred_non_pdf_deepdoc = doc_type
                break
        if inferred_non_pdf_deepdoc:
            target_doc_type = inferred_non_pdf_deepdoc
    if target_doc_type == "md":
        target_doc_type = "markdown"
    elif target_doc_type in {"xlsx", "xls"}:
        target_doc_type = "excel"
    elif target_doc_type == "pptx":
        target_doc_type = "ppt"
    elif target_doc_type == "csv":
        target_doc_type = "txt"
    elif target_doc_type not in TEXT_DOC_TYPES:
        target_doc_type = "pdf"

    attr_name = "json_file" if target_doc_type == "json" else target_doc_type
    text_cfg: TextTypeParsingConfig | PdfParsingConfig
    text_cfg = getattr(text, attr_name, text.pdf)
    result["strategy"] = text_cfg.strategy if file_type else result.get("strategy", text_cfg.strategy)

    if target_doc_type == "pdf":
        pdf_cfg = text.pdf
        result["ocr_enabled"] = pdf_cfg.ocr_enabled
        if pdf_cfg.strategy == "deepdoc" and pdf_cfg.parser:
            result["deepdoc_parser_id"] = PDF_PARSER_TO_LEGACY_ID[pdf_cfg.parser]
            if pdf_cfg.parser in ("layout", "plain", "vision"):
                result["deepdoc_pdf_mode"] = pdf_cfg.parser
    elif text_cfg.strategy == "deepdoc":
        result["deepdoc_parser_id"] = target_doc_type

    if parsed.image:
        result["image_strategy"] = parsed.image.strategy
        result["vlm_description_enabled"] = parsed.image.strategy == "vlm"
        if parsed.image.vlm_model:
            result["vlm_model"] = parsed.image.vlm_model

    if parsed.video:
        result["video"] = parsed.video.model_dump(exclude_none=True)
        if parsed.video.vlm_description_enabled:
            result["vlm_description_enabled"] = True
        if parsed.video.vlm_model:
            result["vlm_model"] = parsed.video.vlm_model

    if parsed.audio:
        result["audio"] = parsed.audio.model_dump(exclude_none=True)

    return result
