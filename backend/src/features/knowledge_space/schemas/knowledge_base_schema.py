"""知识库请求/响应 Schema：切分/解析配置结构（含旧扁平配置的向后兼容迁移）。"""

from datetime import datetime
from typing import Any, Literal

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
LEGACY_SPLITTING_STRATEGY_ALIASES: dict[str, str] = {
    "sentence": "recursive",  # legacy audio transcript strategy
    "fixed": "fixed_size",    # legacy video description strategy
}


def _migrate_legacy_splitting_strategy(value: Any) -> Any:
    """Normalize legacy splitting strategy names to the current Literal set.

    Applied to the top-level strategy. Unknown values are left untouched so they
    still surface a clear validation error rather than being silently coerced to a
    wrong strategy. Legacy audio/video sub-key overrides have been removed; any
    residual sub-keys are dropped by SplittingConfig(extra="ignore").
    """
    if not isinstance(value, dict):
        return value

    normalized = dict(value)
    top_strategy = normalized.get("strategy")
    if isinstance(top_strategy, str):
        normalized["strategy"] = LEGACY_SPLITTING_STRATEGY_ALIASES.get(
            top_strategy, top_strategy
        )

    return normalized


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

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_strategy(cls, value):
        """迁移旧切分策略别名到现名（before 校验器，就地改写 dict）。"""
        return _migrate_legacy_splitting_strategy(value)


# ========== Parsing config ==========


PdfParserName = Literal["full"]

LegacyDeepDocParserId = Literal[
    "pdf_full",
    "pdf_plain",
    "pdf_layout",
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


class DeepDocOnlyParsingConfig(BaseModel):
    """Excel/PPT/EPUB 解析配置——default 模式无 reader（DocumentRegistry 未注册，
    运行时报 Unsupported file type），仅支持 deepdoc。"""

    model_config = ConfigDict(extra="ignore")

    strategy: Literal["deepdoc"] = Field(default="deepdoc")


class PdfParsingConfig(TextTypeParsingConfig):
    """PDF parsing config."""

    parser: PdfParserName | None = Field(default=None)

    @model_validator(mode="after")
    def validate_parser_usage(self):
        # default 模式不用 parser（运行时 build_runtime_parsing_config 在
        # strategy=default 时忽略 parser 字段，仅 deepdoc 时取用）。深度合并
        # 会产生 strategy=default + 残留 parser 的组合——用户从 deepdoc 切回
        # default 时未显式清 parser，旧值残留；运行时本就忽略该字段，此处自动
        # 清空而非报错，避免 update 返回时 response 构造触发 500（KB 配置
        # update 实测）。parser 原值仍在 DB，切回 deepdoc 时恢复。
        """strategy=default 时自动清空残留 parser 字段（防旧值触发响应构造 500）。"""
        if self.strategy == "default" and self.parser is not None:
            self.parser = None
        return self


class TextParsingConfig(BaseModel):
    """Text parsing config grouped by document type."""

    model_config = ConfigDict(extra="ignore")

    pdf: PdfParsingConfig = Field(default_factory=PdfParsingConfig)
    docx: TextTypeParsingConfig = Field(default_factory=TextTypeParsingConfig)
    excel: DeepDocOnlyParsingConfig = Field(default_factory=DeepDocOnlyParsingConfig)
    ppt: DeepDocOnlyParsingConfig = Field(default_factory=DeepDocOnlyParsingConfig)
    epub: DeepDocOnlyParsingConfig = Field(default_factory=DeepDocOnlyParsingConfig)
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
    vlm_model: str | None = Field(
        default=None,
        description="VLM 模型名称（strategy=vlm 时必填，留空将抛错要求显式选择，不做默认回退）",
    )


class VideoParsingConfig(BaseModel):
    """Video parsing config.

    strategy（视频解析策略，预设映射到抽帧/去重/描述三阶段组合）：
    - "simple": 固定间隔抽帧 + 不去重 + 逐帧单图描述（默认，等价旧行为）
    - "scene": 场景切换抽帧（直方图差）+ 不去重 + 逐帧单图描述
    - "dedup": 固定间隔 + 直方图相似度去重 + 逐帧单图描述
    - "grouped": 固定间隔 + 不去重 + 多帧一组喂 VLM 多图生成连贯描述
    - "rewrite": 固定间隔 + 不去重 + 逐帧描述后 LLM 重写连贯（保留时间锚点）
    - "frame_seq": 固定间隔抽帧的整段帧序列以伪视频喂 VLM（模型感知时序），
      需 VLM 协议配 openai_video；只接固定间隔抽帧（scene 帧时刻不均匀，fps 语义失效）
    - "video_native": 切片直输 VLM（模型直接看视频，慢切换场景最优；录屏
      不推荐——服务商内部分辨率压缩丢 UI 小字）。需 VLM 协议配 openai_video
      + minio.public_endpoint（外部 VLM 下载切片）；抽帧强制走 scene
      （切换点即聚片边界）；被服务商拒视频输入时自动降级 frame_seq（可关）。
    """

    model_config = ConfigDict(extra="ignore")

    strategy: Literal[
        "simple", "scene", "dedup", "grouped", "rewrite", "frame_seq", "video_native"
    ] = Field(
        default="simple",
        description="视频解析策略：7 预设（抽帧/去重/描述三阶段组合）",
    )
    frame_interval: float = Field(default=5.0, ge=0.5, le=60.0)
    max_frames: int = Field(default=60, ge=1, le=1000)
    vlm_description_enabled: bool = Field(default=False)
    vlm_model: str | None = Field(default=None)
    # VLM 主模型因配额/鉴权类错误失败时，回退到的备用 VLM 模型名（用户在模型管理中配置过的）。
    vlm_fallback_model: str | None = Field(default=None)
    # 当所有帧的 VLM 描述均因配额/鉴权类错误失败时，是否跳过 VLM 并写一条占位描述，
    # 而不是让整个文档任务失败。默认 False（fail fast，抛业务异常提示用户）。
    vlm_skip_on_quota_error: bool = Field(default=False)
    # 高级参数（可选，留空用引擎层默认）：
    # 场景抽帧切换点阈值（strategy=scene），0~1，默认 0.3。
    scene_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    # 场景抽帧切换点间隔保护（strategy=scene，秒），默认 2.0。动作密集视频
    # （下锅/倒料 2-3 秒）可调小到 0.5，让相邻切换点都留帧，不再被间隔保护吞掉。
    scene_min_interval: float | None = Field(default=None, ge=0.1, le=10.0)
    # 去重相似度阈值（strategy=dedup），0~1，默认 0.95。
    dedup_similarity_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    # 分组大小（strategy=grouped），每组喂 VLM 多图的帧数，默认 3。
    group_size: int | None = Field(default=None, ge=1, le=20)
    # 帧序列伪视频每段帧数上限（strategy=frame_seq），默认 512（DashScope 帧列表
    # 单次请求硬限 4-512 张）；长视频超限自动分段，尾段过短并入前段。
    frame_seq_chunk_frames: int | None = Field(default=None, ge=8, le=512)
    # ===== S4 视频直输（strategy=video_native）=====
    # 单片时长上限（秒），默认 540（DashScope 视频时长硬限 10min 留 60s 裕量；
    # 尾片并入后前片最长 540+min_tail，仍 < 600s 硬限）。
    video_native_chunk_sec: float | None = Field(default=None, ge=30.0, le=540.0)
    # 尾片并入阈值（秒），默认 30：尾片短于该值并入前片。
    video_native_min_tail_sec: float | None = Field(default=None, ge=0.0, le=120.0)
    # 片间并发上限，默认 2（切片上传+直输请求均比逐帧重，与逐帧并发分档）。
    video_native_concurrency: int | None = Field(default=None, ge=1, le=4)
    # 服务商明确拒绝视频输入（VideoInputNotSupportedError）时是否自动降级
    # frame_seq 帧序列策略，默认 True；关闭则直接失败（fail fast）。
    video_native_fallback_to_frame_seq: bool = Field(default=True)
    # ===== 音轨 ASR 融合（批2 c3/c4）=====
    # 开启后提取原始视频音轨做 ASR 转写，旁白按时间归入帧描述行（双轨融合）。
    transcribe_audio: bool = Field(default=False)
    # 音轨 ASR 模型名（留空 = 部署默认本地档，与音频文档默认一致）。
    asr_model: str | None = Field(default=None)
    # ASR 语言提示（留空 = 自动检测）。
    language: str | None = Field(default=None)
    # 音轨 ASR 热词（语义与 AudioParsingConfig.hotwords 一致；仅本地协议生效）。
    hotwords: list[str] | None = Field(default=None, max_length=100)
    # ===== 步骤综合（批2 c4）=====
    # 开启后在帧级 chunks 之外追加全局步骤综合 pass：LLM 汇总双轨描述输出
    # 带时间区间的操作步骤条目，双层覆盖率校验（帧层+旁白层）防遗漏。
    steps_enabled: bool = Field(default=False)
    # 步骤综合所用 LLM 模型名（留空 = 用户默认 LLM）。
    steps_llm_model: str | None = Field(default=None)
    # 步骤条目上限（防超长视频步骤爆炸），默认 30。
    steps_max_steps: int = Field(default=30, ge=1, le=200)


class AudioParsingConfig(BaseModel):
    """音频解析配置（KB 级）。

    asr_model 语义：None/空 = 走本地 faster-whisper（引擎档位由 YAML
    knowledge_base.parsing.local_whisper_model 决定，默认 large-v3，开发机
    降档配置）；云端模型名（如 whisper-1 / paraformer-v2）须在模型管理中
    配置同名凭证。
    """

    model_config = ConfigDict(extra="ignore")

    # 修复历史陷阱：旧默认值 "whisper-1" 会让存了 audio 子节但未显式选模型的
    # KB 去查不存在的云端凭证并抛 PermanentProcessingError——与运行时空值
    # 默认（本地 faster-whisper）语义不一致。现统一为 None = 本地默认。
    asr_model: str | None = Field(default=None)
    language: str | None = Field(default=None)
    # ASR 热词（领域词表，如产品名/人名/术语）：本地 faster-whisper 经原生
    # hotwords 参数注入解码；云端轨暂不支持自由热词（DashScope 录音文件识别
    # 仅支持控制台预注册的 phrase_id），传入时告警忽略。上限 100 条防解码
    # prompt 膨胀拖慢转写。
    hotwords: list[str] | None = Field(default=None, max_length=100)


class ParsingConfig(BaseModel):
    """Top-level parsing config."""

    model_config = ConfigDict(extra="ignore")

    strategy: Literal["default", "deepdoc"] | None = Field(default=None)
    deepdoc_parser_id: LegacyDeepDocParserId | None = Field(default=None)
    deepdoc_pdf_mode: Literal["full", "plain"] | None = Field(default=None)
    # 公式识别（pix2text-mfr）：None = 默认开启（模型就绪时识别 equation 区域输出 LaTeX），
    # 显式 False 关闭。模型缺失时解析器 WARNING 软降级（公式保留 OCR 文本）。
    deepdoc_formula_recognition: bool | None = Field(default=None)
    text: TextParsingConfig | None = Field(default=None)
    image: ImageParsingConfig | None = Field(default=None)
    video: VideoParsingConfig | None = Field(default=None)
    audio: AudioParsingConfig | None = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_parsing(cls, value):
        """迁移旧扁平解析配置到按模态分组的新结构（before 校验器）。

        Args:
            value: 校验前的原始入参，非 dict 原样返回。

        Returns:
            迁移合并后的配置 dict；无旧键时原样返回。
        """
        if not isinstance(value, dict):
            return value

        # 迁移旧 image.strategy="ocr" → "deepdoc_ocr"
        image_cfg = value.get("image")
        if isinstance(image_cfg, dict) and image_cfg.get("strategy") == "ocr":
            image_cfg = dict(image_cfg)
            image_cfg["strategy"] = "deepdoc_ocr"
            value = dict(value)
            value["image"] = image_cfg

        # 迁移旧 video.strategy="dedup_grouped" → "grouped"
        # dedup_grouped 预留未实现已移除；旧配置降级到 grouped（保留分组描述，
        # 丢弃未实现的图像 embedding 去重），避免 schema 收紧后反序列化 500。
        video_cfg = value.get("video")
        if isinstance(video_cfg, dict) and video_cfg.get("strategy") == "dedup_grouped":
            video_cfg = dict(video_cfg)
            video_cfg["strategy"] = "grouped"
            value = dict(value)
            value["video"] = video_cfg

        # 迁移已移除的 PDF parser（docling/mineru/opendataloader/paddleocr/somark/
        # tcadp 远程服务未实现；plain 已随前端「default/deepdoc 两选」收敛移除）
        # → full，避免 schema 收紧后旧配置反序列化 500。
        _REMOVED_PDF_PARSERS = {
            "docling", "mineru", "opendataloader", "paddleocr", "somark", "tcadp", "plain",
        }
        # Excel/PPT/EPUB default 模式无 reader（DocumentRegistry 未注册，运行时
        # 报 Unsupported file type），旧配置 default 迁移到 deepdoc。
        _DEEPDOC_ONLY_DOC_TYPES = ("excel", "ppt", "epub")
        text_cfg = value.get("text")
        if isinstance(text_cfg, dict):
            new_text = dict(text_cfg)
            text_changed = False
            pdf_cfg = text_cfg.get("pdf")
            if isinstance(pdf_cfg, dict) and pdf_cfg.get("parser") in _REMOVED_PDF_PARSERS:
                pdf_cfg = dict(pdf_cfg)
                pdf_cfg["parser"] = "full"
                new_text["pdf"] = pdf_cfg
                text_changed = True
            for doc_type in _DEEPDOC_ONLY_DOC_TYPES:
                dt_cfg = text_cfg.get(doc_type)
                if isinstance(dt_cfg, dict) and dt_cfg.get("strategy", "default") == "default":
                    dt_cfg = dict(dt_cfg)
                    dt_cfg["strategy"] = "deepdoc"
                    new_text[doc_type] = dt_cfg
                    text_changed = True
            if text_changed:
                value = dict(value)
                value["text"] = new_text

        legacy_keys = {
            "strategy",
            "deepdoc_parser_id",
            "deepdoc_pdf_mode",
            "deepdoc_formula_recognition",
            # ocr_enabled 已随 Tesseract OCR 兜底删除，保留在 legacy 键集合里
            # 让旧配置仍触发迁移分支（值本身被丢弃，不再写入新结构）
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
        migrated_pdf_mode = (
            "full" if pdf_mode in {"layout", "vision", "full", "plain"}
            else None
        )
        vlm_enabled = bool(legacy.get("vlm_description_enabled", False))
        vlm_model = legacy.get("vlm_model")

        migrated: dict[str, Any] = {
            "strategy": strategy,
            "deepdoc_parser_id": parser_id,
            "deepdoc_pdf_mode": migrated_pdf_mode,
            "deepdoc_formula_recognition": legacy.get("deepdoc_formula_recognition"),
            "text": {
                "pdf": {"strategy": "default"},
                "docx": {"strategy": "default"},
                # Excel/PPT/EPUB 仅支持 deepdoc（default 模式无 reader）
                "excel": {"strategy": "deepdoc"},
                "ppt": {"strategy": "deepdoc"},
                "epub": {"strategy": "deepdoc"},
                "markdown": {"strategy": "default"},
                "html": {"strategy": "default"},
                "txt": {"strategy": "default"},
                "json_file": {"strategy": "default"},
            },
            "video": legacy.get("video"),
            "audio": legacy.get("audio"),
        }

        parser_to_type: dict[str, tuple[str, str | None]] = {
            "pdf_full": ("pdf", "full"),
            "pdf_layout": ("pdf", "full"),
            "pdf_plain": ("pdf", "full"),
            "pdf_vision": ("pdf", "full"),
            # 6 个远程 parser 未实现已从 PdfParserName 移除，旧 deepdoc_parser_id 迁移到 full
            "pdf_docling": ("pdf", "full"),
            "pdf_mineru": ("pdf", "full"),
            "pdf_opendataloader": ("pdf", "full"),
            "pdf_paddleocr": ("pdf", "full"),
            "pdf_somark": ("pdf", "full"),
            "pdf_tcadp": ("pdf", "full"),
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
            # 旧配置可能只带 deepdoc_pdf_mode 没带 deepdoc_parser_id，按模式补 parser
            if migrated_pdf_mode:
                migrated["text"]["pdf"]["parser"] = migrated_pdf_mode

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
            if key == "deepdoc_pdf_mode":
                # 保留迁移后的值（layout/vision → full），不被原始旧值覆盖
                continue
            merged[key] = current_value

        return merged


# ========== Question generation ==========


class QuestionLLMConfig(BaseModel):
    """Question-generation LLM config."""

    model: str | None = Field(default=None)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    max_tokens: int = Field(default=2048, ge=100, le=8192)


class QuestionGenerationConfig(BaseModel):
    """Question-generation config."""

    enabled: bool = Field(default=False)
    llm: QuestionLLMConfig | None = Field(default=None)
    max_questions_per_chunk: int = Field(default=5, ge=1, le=20)
    prompt_template: str | None = Field(default=None, max_length=4000)


# ========== Wiki generation ==========


class WikiGenerationConfig(BaseModel):
    """Wiki 自动生成配置（文档解析完成后 LLM 整理互链 Markdown 页面）。

    引用接地/合并/去重等系统规则不开放自定义；content_instructions 只控制
    语气、结构与侧重点，extraction_instructions 只控制抽取侧重。
    """

    enabled: bool = Field(default=False)
    llm: QuestionLLMConfig | None = Field(default=None)
    granularity: Literal["focused", "standard", "exhaustive"] = Field(
        default="standard",
        description="抽取粒度：focused=仅主要主题, standard=主题+实质性讨论的实体概念, exhaustive=穷举",
    )
    max_pages_per_ingest: int = Field(default=50, ge=1, le=500, description="单文档生成/更新的页面上限")
    content_instructions: str | None = Field(default=None, max_length=2000)
    extraction_instructions: str | None = Field(default=None, max_length=2000)
    boost_factor: float | None = Field(
        default=None,
        ge=0.1,
        le=10.0,
        description="检索时 wiki 页命中加权系数；None=默认 1.3（对齐 WeKnora wiki_boost）。"
        "消费端见 search_service 的 wiki_boost_factor 解析，factor 参与 RetrievalQuery 缓存键",
    )


# ========== Full KB config ==========


class KnowledgeBaseConfig(BaseModel):
    """Full knowledge-base config."""

    space_type: list[Literal["text", "image", "video", "audio"]] = Field(
        default_factory=lambda: ["text"],
        description="数据模态列表：text=文本文档, image=图片, video=视频, audio=音频",
    )
    description: str = Field(default="", max_length=2000)
    splitting: SplittingConfig = Field(default_factory=SplittingConfig)
    parsing: ParsingConfig = Field(default_factory=ParsingConfig)
    question_generation: QuestionGenerationConfig = Field(default_factory=QuestionGenerationConfig)
    wiki: WikiGenerationConfig = Field(default_factory=WikiGenerationConfig)


# ========== Request / response schemas ==========


class KnowledgeBaseCreate(BaseModel):
    """Create KB request."""

    name: str = Field(..., min_length=1, max_length=100)
    config: KnowledgeBaseConfig | None = Field(default=None)


class KnowledgeBaseUpdate(BaseModel):
    """Update KB request."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    # 归档/激活（1=活跃 2=归档）；0（删除）不在此通道，删除走 DELETE 端点
    status: Literal[1, 2] | None = Field(default=None)
    config: KnowledgeBaseConfig | None = Field(default=None)


class KnowledgeBaseResponse(BaseModel):
    """Knowledge-base response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    space_id: int
    name: str
    creator_id: int
    config: dict[str, Any] | None = None
    storage: dict[str, Any] | None = None
    status: int = 1
    stats: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("status")
    def serialize_status(self, value) -> int:
        """状态枚举序列化为 int（None 兜底 1）。

        Args:
            value: 待序列化的状态值，可能是枚举、整数或 None。

        Returns:
            枚举取其 value；整数原样返回；None 兜底 1（活跃）。
        """
        if hasattr(value, "value"):
            return value.value
        return int(value) if value is not None else 1


class KnowledgeBaseListResponse(BaseModel):
    """Knowledge-base list response."""

    items: list[KnowledgeBaseResponse]
    total: int
    skip: int
    limit: int


class KnowledgeBaseConfigUpdate(BaseModel):
    """Partial config update request."""

    space_type: list[Literal["text", "image", "video", "audio"]] | None = Field(
        default=None,
        description="数据模态列表：text=文本文档, image=图片, video=视频, audio=音频",
    )
    splitting: SplittingConfig | None = Field(default=None)
    parsing: ParsingConfig | None = Field(default=None)
    question_generation: QuestionGenerationConfig | None = Field(default=None)


class KnowledgeBaseConfigResponse(BaseModel):
    """Knowledge-base config response."""

    model_config = ConfigDict(from_attributes=True)

    kb_id: int
    name: str
    config: KnowledgeBaseConfig
    stats: dict[str, Any]


PDF_PARSER_TO_LEGACY_ID: dict[str, str] = {
    "full": "pdf_full",
}


TEXT_DOC_TYPES = ("pdf", "docx", "excel", "ppt", "epub", "markdown", "html", "txt", "json")


def build_runtime_parsing_config(parsing: dict[str, Any] | None, file_type: str | None = None) -> dict[str, Any]:
    """
    Convert the new nested parsing config into the legacy runtime parsing shape.

    Runtime parsers still expect legacy keys such as:
    - strategy
    - deepdoc_parser_id
    - deepdoc_pdf_mode
    - vlm_description_enabled
    - vlm_model
    """
    parsed = ParsingConfig.model_validate(parsing or {})
    result: dict[str, Any] = {}
    if parsed.strategy is not None:
        result["strategy"] = parsed.strategy
    if parsed.deepdoc_parser_id is not None:
        result["deepdoc_parser_id"] = parsed.deepdoc_parser_id
    if parsed.deepdoc_pdf_mode is not None:
        result["deepdoc_pdf_mode"] = parsed.deepdoc_pdf_mode
    if parsed.deepdoc_formula_recognition is not None:
        result["deepdoc_formula_recognition"] = parsed.deepdoc_formula_recognition

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
        if pdf_cfg.strategy == "deepdoc" and pdf_cfg.parser:
            result["deepdoc_parser_id"] = PDF_PARSER_TO_LEGACY_ID[pdf_cfg.parser]
            if pdf_cfg.parser in ("full", "plain"):
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
        result["video_strategy"] = parsed.video.strategy
        if parsed.video.vlm_description_enabled:
            result["vlm_description_enabled"] = True
        if parsed.video.vlm_model:
            result["vlm_model"] = parsed.video.vlm_model

    if parsed.audio:
        result["audio"] = parsed.audio.model_dump(exclude_none=True)

    return result
