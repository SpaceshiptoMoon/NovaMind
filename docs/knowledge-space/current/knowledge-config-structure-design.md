# Knowledge Base Config Structure Design

## Purpose

This document defines the proposed next-generation knowledge-base config structure for the `knowledge_space` module.

It is intended to serve as a formal design document before implementation.

The main change is:

- move from parser-centric config
- to data-type-centric config

Instead of choosing one global parsing method for all text-like files, the new structure organizes config by modality and then by document type.

## Current Project Status

The current project already has:

- knowledge-base config APIs
- backend config schema and validation
- frontend knowledge-base config page
- runtime logic for text, image, video, and audio pipelines

The current implementation is moving to a modality-first structure:

```json
{
  "parsing": {
    "strategy": "default | deepdoc",
    "deepdoc_parser_id": "pdf_full | ...",
    "deepdoc_pdf_mode": "full | plain",
    "ocr_enabled": false,
    "vlm_description_enabled": false,
    "vlm_model": null,
    "video": {
      "frame_interval": 5.0,
      "max_frames": 60
    },
    "audio": {
      "asr_model": "whisper-1",
      "language": null
    }
  }
}
```

This document is the implementation reference for the current codebase.

## Design Goals

1. Make config easier for frontend users to understand.
2. Organize parsing settings by data source, not by internal parser implementation.
3. Avoid exposing backend-only parser IDs directly to frontend users.
4. Make it easier to extend parsing strategies for individual document types.
5. Keep runtime migration low-risk by allowing a compatibility mapping layer.

## Target Config Structure

Recommended structure:

```json
{
  "parsing": {
    "text": {
      "pdf": {
        "strategy": "default | deepdoc",
        "parser": "layout | plain | vision | docling | mineru | opendataloader | paddleocr | somark | tcadp",
        "ocr_enabled": false
      },
      "docx": {
        "strategy": "default | deepdoc"
      },
      "excel": {
        "strategy": "default | deepdoc"
      },
      "ppt": {
        "strategy": "default | deepdoc"
      },
      "epub": {
        "strategy": "default | deepdoc"
      },
      "markdown": {
        "strategy": "default | deepdoc"
      },
      "html": {
        "strategy": "default | deepdoc"
      },
      "txt": {
        "strategy": "default | deepdoc"
      },
      "json": {
        "strategy": "default | deepdoc"
      }
    },
    "image": {
      "ocr_enabled": false,
      "vlm_description_enabled": false,
      "vlm_model": null
    },
    "video": {
      "frame_interval": 5.0,
      "max_frames": 60
    },
    "audio": {
      "asr_model": "whisper-1",
      "language": null
    }
  }
}
```

## Key Design Principle

Old model:

- choose parsing method first
- then infer which file types it applies to

New model:

- choose data type first
- then choose parsing method for that data type

This is especially important for `text`, where different document types have different parsing requirements.

## Text Parsing Structure

Text parsing is organized by document type:

```json
{
  "parsing": {
    "text": {
      "pdf": { "strategy": "default | deepdoc", "parser": "full", "ocr_enabled": false },
      "docx": { "strategy": "default | deepdoc" },
      "excel": { "strategy": "deepdoc" },
      "ppt": { "strategy": "deepdoc" },
      "epub": { "strategy": "deepdoc" },
      "markdown": { "strategy": "default | deepdoc" },
      "html": { "strategy": "default | deepdoc" },
      "txt": { "strategy": "default | deepdoc" },
      "json": { "strategy": "default | deepdoc" }
    }
  }
}
```

Note: `excel` / `ppt` / `epub` only support `deepdoc` — the default mode has no
reader registered in `DocumentRegistry`, so a `default`-strategy request fails
at runtime with an unsupported-file-type error. The backend schema pins these
types to `strategy = "deepdoc"`.

### Why this structure

- users think in terms of file types
- frontend forms are easier to build by document type
- per-type strategy extension becomes straightforward
- parser-specific settings stay local to the relevant type

## PDF-Specific Rules

PDF is the only text subtype that currently needs a richer config model.

Current structure:

```json
{
  "pdf": {
    "strategy": "default | deepdoc",
    "parser": "full",
    "ocr_enabled": false
  }
}
```

### Behavior rules

- `strategy` is required.
- `strategy=default`
  - `parser` must not be provided.
- `strategy=deepdoc`
  - `parser` is optional; currently the only valid value is `full`
    (the upstream-aligned per-box fusion pipeline). The historical `plain`
    mode lives on as a compatibility alias via `deepdoc_pdf_mode`.
- `ocr_enabled` is independent and may remain available.

### Parser ID history (2026-08/09 convergence)

The backend previously exposed multiple PDF parser ids
(`pdf_layout`, `pdf_vision`, `pdf_docling`, `pdf_mineru`, `pdf_opendataloader`,
`pdf_paddleocr`, `pdf_somark`, `pdf_tcadp`). All of them are now **legacy
values only**: the schema accepts them in `LegacyDeepDocParserId` and migrates
them to `parser = "full"` (mode `full`/`plain`). The remote-service parser
implementations were removed from the runtime; `pdf_layout`/`pdf_vision`
collapse into `full` inside the DeepDoc runtime parser. Do not expose these
legacy ids in new frontend forms.

### Why `parser` should be frontend-friendly

Frontend should not expose backend internal IDs like `pdf_full`. It should
expose stable, user-readable values and let the backend map them to internal
parser IDs.

## Backend Mapping Rule

Current mapping (in `knowledge_base_schema.py`):

```python
PdfParserName = Literal["full"]  # frontend-facing value

# legacy deepdoc_parser_id values are migrated on read, e.g.:
#   "pdf_full" | "pdf_layout" | "pdf_vision" | "pdf_docling" | "pdf_mineru"
#   | "pdf_opendataloader" | "pdf_paddleocr" | "pdf_somark" | "pdf_tcadp"
#     → ("pdf", "full")
#   "pdf_plain" → ("pdf", "plain")
```

This allows:

- frontend to remain stable and readable
- backend runtime to continue using existing parser infrastructure
- old persisted configs to keep working without a data migration

## Image Parsing Structure

Current implemented structure:

```json
{
  "parsing": {
    "image": {
      "strategy": "vlm | deepdoc_ocr",
      "vlm_description_enabled": false,
      "vlm_model": null
    }
  }
}
```

### Rules

- `strategy=deepdoc_ocr` (migrated from the historical value `ocr`)
  - uses DeepDoc's OCR path; `vlm_model` is ignored.
- `strategy=vlm`
  - generates a VLM description for the image; `vlm_model` is optional.
  - image embedding always goes through VLM description + text embedding.

## Video Parsing Structure

Recommended structure:

```json
{
  "parsing": {
    "video": {
      "strategy": "simple | scene | dedup | grouped | rewrite | frame_seq | video_native",
      "frame_interval": 5.0,
      "max_frames": 60,
      "vlm_model": null,
      "vlm_fallback_model": null,
      "vlm_skip_on_quota_error": false,
      "scene_threshold": null,
      "scene_min_interval": null,
      "dedup_similarity_threshold": null,
      "group_size": null,
      "frame_seq_chunk_frames": null,
      "video_native_chunk_sec": null,
      "video_native_min_tail_sec": null,
      "video_native_concurrency": null,
      "video_native_fallback_to_frame_seq": true,
      "transcribe_audio": false,
      "asr_model": null,
      "language": null,
      "steps_enabled": false,
      "steps_llm_model": null,
      "steps_max_steps": 30
    }
  }
}
```

### 七种策略（抽帧/去重/描述三阶段组合预设）

| strategy | 抽帧 | 描述 | 适用 | 备注 |
|---|---|---|---|---|
| `simple` | 固定间隔 | 逐帧单图 | 默认 | 采样盲区：2 秒动作 ~60% 概率漏 |
| `scene` | 场景切换点 | 逐帧单图 | 镜头分明的视频 | 切换点阈值/间隔保护可调 |
| `dedup` | 固定间隔+去重 | 逐帧单图 | 静态画面为主的视频 | 直方图相似度去重 |
| `grouped` | 固定间隔 | 多帧一组多图 | 短视频连贯描述 | 无时序感知 |
| `rewrite` | 固定间隔 | 逐帧+LLM 重写 | 逐帧结果润色 | 保留时间锚点 |
| `frame_seq` | 固定间隔 | 整段帧序列伪视频 | 全场景通用（推荐） | 需 VLM 协议 `openai_video` |
| `video_native` | 场景切换点 | 切片直输 | 慢切换（会议/讲座/访谈） | 需 `openai_video` + `minio.public_endpoint`；录屏不推荐 |

### S3 `frame_seq` 帧序列伪视频（2026-10）

整段帧以 `{"type":"video","video":[帧 data URL 列表],"fps":N}` 喂 VLM，模型感知时序。
真实 API 实测（qwen3.8-27b，5 场景矩阵）全场景零翻车、input token 最低。

- **协议要求**：VLM 模型的协议必须配 `openai_video`（专用视频客户端
  `OpenAICompatibleVideoLLM`，模型管理里把所选 VLM 协议改为 `openai_video`）。
  客户端缺 `generate_text_from_frames` 时任务直接失败并提示改协议（fail fast）。
- **只接固定间隔抽帧**：scene 帧时刻不均匀，`fps` 语义失效。
- **长视频分段**：DashScope 帧列表单次请求硬限 4-512 张，超限按
  `frame_seq_chunk_frames`（默认 512）固定 size 分段，尾段 < 8 帧并入前段；
  段间并发默认 2（伪视频请求体大，不与逐帧并发同档）。
- **时间校准**：每段 prompt 注入帧时刻表（`帧#0=12.5s ...`），修实测发现的
  ~1s 系统性偏移；chunk 时间区间仍由代码绝对时间构建，模型文本时间只给人看。

### S4 `video_native` 视频直输（2026-10）

按场景切换点聚片，每片 ffmpeg `-c copy` 流复制切出（无重编码）上传临时
MinIO 对象，模型直接看视频（`{"type":"video_url","video_url":{"url":...}}`）。
慢切换场景最优（切换定位准+结构推理+token 省）；快切换时间戳漂移 1-3s
（机制性，代码侧时间权威兜底）；录屏翻车（服务商内部分辨率压缩丢 UI 小字，
文档标注不推荐）。

- **协议/网络要求**：VLM 协议 `openai_video`；`minio.public_endpoint` 必须配置
  （外部 VLM 服务下载切片用，缺失时告警但片描述会失败）。
- **聚片**：场景切换点作片边界（片内单一场景段）；切换点间距超
  `video_native_chunk_sec`（默认 540s，DashScope 10min 硬限留 60s 裕量）的
  区间均分切小；尾片 < `video_native_min_tail_sec`（默认 30s）并入前片。
- **临时对象生命周期**：`{base}_vtmp/` 前缀即用即删（无论成败 finally 清理）。
- **降级链**：服务商明确拒绝视频输入（`VideoInputNotSupportedError`）且
  `video_native_fallback_to_frame_seq=true`（默认）→ 告警并自动降级
  frame_seq 全套；其它错误不降级（fail fast）。
- **时间权威在代码侧**：chunk 时间区间全部由代码绝对时间构建；prompt 注入
  `{t0}` 片起始绝对秒做双重校正，但模型输出的时间只给人看不参与对齐。

### Rules

- `frame_interval` and `max_frames` work together (except `scene` / `video_native`).
- `vlm_model` 必选：留空任务直接失败（不回退用户默认、不串用 image 的模型）。
- `vlm_fallback_model` 是用户显式配置的备用模型，配额/鉴权失败时回退一次。
- `vlm_skip_on_quota_error=true` 时全帧配额失败写占位描述而非任务失败。
- 所有策略共用音轨 ASR 融合（`transcribe_audio`）与步骤综合（`steps_enabled`）——
  S3/S4 的段/片产出与 grouped 同构（`frame_groups` 锚点展开），下游零改动复用。

## Audio Parsing Structure

Recommended structure:

```json
{
  "parsing": {
    "audio": {
      "asr_model": "whisper-1",
      "language": null
    }
  }
}
```

### Rules

- `asr_model` and `language` are not mutually exclusive.
- `language=null` means auto-detect.

## Splitting Structure

The current splitting model is mostly reusable and does not require a major redesign.

Recommended to keep:

- top-level text splitting
- `splitting.audio`
- `splitting.video`

Current image splitting overrides were previously removed and should not be reintroduced without a concrete runtime need.

## Wiki Generation Structure

The `wiki` config section (2026-09) controls post-parse wiki page generation
(see `docs/knowledge-space/current/wiki-architecture.md` for the full pipeline).

```json
{
  "wiki": {
    "enabled": false,
    "llm": null,
    "granularity": "focused | standard | exhaustive",
    "max_pages_per_ingest": 50,
    "content_instructions": null,
    "extraction_instructions": null
  }
}
```

Rules:

- `enabled` gates the whole feature; documents ingested while disabled never
  trigger wiki generation (re-enabling only affects future parses; use
  `POST .../wiki/rebuild` to backfill existing documents).
- `llm` reuses `QuestionLLMConfig`; when null the KB-level default LLM applies.
- `granularity` controls candidate extraction density (focused=main topics
  only, standard=substantive entities/concepts, exhaustive=exhaustive).
- `content_instructions` / `extraction_instructions` only steer tone, structure
  and extraction focus. Citation grounding, merge and dedup rules are NOT
  user-configurable.
- Wiki pages live in MySQL (source of truth) and, once **published**, are synced into Elasticsearch as `chunk_type=wiki_page` documents (`services/wiki_es_sync.py`, 2026-09 批5 起), participating in retrieval with wiki `boost_factor` weighting (default 1.3).

## What Already Exists in the Project

The following logic already exists and can be reused:

- KB config API endpoints
- config deep-merge update behavior
- `default | deepdoc` text parsing strategy
- internal DeepDoc parser ID support
- OCR toggle support
- image VLM description support
- video frame extraction config
- audio ASR config
- question generation config
- wiki generation config (`config.wiki`, gated by `enabled`)

Relevant files:

- [backend/src/features/knowledge_space/api/knowledge_base_routes.py](../../../backend/src/features/knowledge_space/api/knowledge_base_routes.py)
- [backend/src/features/knowledge_space/schemas/knowledge_base_schema.py](../../../backend/src/features/knowledge_space/schemas/knowledge_base_schema.py)
- [backend/src/features/knowledge_space/services/knowledge_base_service.py](../../../backend/src/features/knowledge_space/services/knowledge_base_service.py)
- [backend/src/features/knowledge_space/services/document_pipeline.py](../../../backend/src/features/knowledge_space/services/document_pipeline.py)
- [backend/src/features/knowledge_space/services/media_processing.py](../../../backend/src/features/knowledge_space/services/media_processing.py)
- [frontend/src/views/space/KbConfigView.vue](../../../frontend/src/views/space/KbConfigView.vue)
- [frontend/src/api/types.ts](../../../frontend/src/api/types.ts)

## Current Implementation Status

The following parts are now implemented:

- nested `parsing.text.<document_type>` config
- per-document-type `strategy`
- PDF-specific conditional validation
- frontend-friendly PDF parser names
- new-structure-to-old-runtime compatibility mapping
- frontend form sections grouped by modality and document type

The following parts still need ongoing polish rather than structural redesign:

- full frontend regression verification across the whole app
- broader integration coverage for live API environments

## Required Refactor Scope

### Backend

Required changes:

1. Redesign config schema
2. Redesign validation logic
3. Add compatibility mapping layer
4. Update runtime config readers to resolve per-file-type config
5. Add tests for the new structure

Primary files:

- `backend/src/features/knowledge_space/schemas/knowledge_base_schema.py`
- `backend/src/features/knowledge_space/services/knowledge_base_service.py`
- `backend/src/features/knowledge_space/services/document_pipeline.py`
- `backend/src/features/knowledge_space/services/media_processing.py`

### Frontend

Required changes:

1. Redesign TypeScript config types
2. Redesign KB config page state shape
3. Redesign config form layout by document type
4. Add conditional UI rules for parser visibility
5. Update request payload builder

Primary files:

- `frontend/src/api/types.ts`
- `frontend/src/views/space/KbConfigView.vue`

### Tests

Required changes:

1. update config API tests
2. add new schema validation tests
3. add compatibility mapping tests
4. update frontend interaction tests if present later

Relevant existing test files:

- `backend/tests/integration/test_knowledge_space_api.py`
- `backend/tests/features/knowledge_space/test_knowledge_config_runtime.py`
- `backend/tests/engines/document/deepdoc/test_deepdoc_runtime.py`

## Recommended Migration Strategy

Recommended rollout order:

1. Add this design doc to the repository.
2. Implement new backend schema.
3. Add a compatibility translation layer from new structure to old runtime parameters.
4. Keep runtime parsers working through the compatibility layer first.
5. Update frontend form and API types.
6. Add and update tests.
7. After migration stabilizes, consider removing old flat config assumptions.

This reduces risk because parser runtime behavior can stay mostly stable while config structure evolves.

## Suggested Validation Rules

Minimum rules to enforce:

- `pdf.strategy` must be one of `default | deepdoc`
- `pdf.strategy=default` forbids `parser`
- `pdf.strategy=deepdoc` allows `parser` (only `full` is currently valid)
- `excel` / `ppt` / `epub` are pinned to `strategy=deepdoc`
- `image.strategy` must be one of `vlm | deepdoc_ocr`
- `video.frame_interval` must remain in `1.0 ~ 60.0`
- `video.max_frames` must remain in `1 ~ 200`

## Implementation Recommendation

This design should be treated as a real implementation plan, not just a note.

It should be used when the team is ready to refactor knowledge-base config from:

- flat parser-oriented config

to:

- nested data-type-oriented config

## Summary

Current project status:

- logic foundation exists
- target structure exists in backend schema and frontend config page
- runtime compatibility layer exists
- backend config/runtime tests have been added
- integration verification still benefits from continued expansion

This document is the formal reference for that refactor.
