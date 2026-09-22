# Knowledge Architecture Navigation

## Purpose

This document describes the current canonical backend knowledge-base structure.

## Final Structure

### Feature Layer（业务编排）

- `backend/src/features/knowledge_space/`
  - 所有权：API、业务编排、持久化、schemas、权限、任务（tasks/）
  - 管道入口与三模态共享后置尾都在 `services/document_pipeline.py` / `services/media_processing.py`
  - Wiki 生成管道在 `services/wiki_ingest_service.py`（解析完成后 LLM 整理互链页面，详见 `wiki-architecture.md`）
  - 直接消费 engines/document 的解析、切分、媒体处理与 DeepDoc 实现

### Engine Layer（纯逻辑实现）

- `backend/src/engines/document/pipeline/` — 解析管道（DocumentLoader / DocumentProcessor / DocumentRegistry）
- `backend/src/engines/document/splitters/` — 切分器（recursive / semantic / fixed / markdown）
- `backend/src/engines/document/converters/` — 文档格式转换器
- `backend/src/engines/document/media/` — 音频（ASR）、视频（抽帧）、VLM、OCR 处理
- `backend/src/engines/document/integrations/deepdoc/` — DeepDoc 集成（vendored，自包含）
  - 依赖方向：R1 全图 import 无环（机器门禁 Tarjan SCC）；engines 不持有 ORM session，
    可按 R1/R4 引 feature 公共面或直收具体类实例（不再要求单向分层）

### Shared Layer（跨 feature 复用）

- `backend/src/shared/document/readers/` — 文档读取器（PDF/DOCX/TXT/HTML/MD）
- `backend/src/shared/document/validation/` — 文件校验
- `backend/src/shared/storage/` — ES/MinIO/Redis 客户端与工厂

## Runtime Flow

```text
features/knowledge_space/services/
  ├── execute_document_pipeline (文本入口)
  ├── process_audio_document  (音频入口)
  ├── process_video_document  (视频入口)
  └── _process_image_document_static (图片入口，独立通路)

三模态（文本/音频/视频）管道形态（后置尾 helper 已下沉 `services/pipeline_steps.py`）：
  解析(转换器/deepdoc) → persist_parsed_text(MD → MinIO)
               → run_post_parse_tail(切分 → 向量化 → QG → 索引)
                   ├── split_md_text / prechunked
                   ├── build_es_chunks（统一 ES chunk 构造器）
                   ├── generate_embeddings
                   ├── generate_questions_for_chunks（由 pipeline_config 控制）
                   └── get_es_client → bulk_index_chunks

图片管道独立，不走共享后置尾（单 chunk、无 QG、es_chunk 形状不同）。

文档成功终态后（可选）触发 Wiki 生成：`tasks/document_tasks.py` → `tasks/wiki_tasks.py`
→ `services/wiki_ingest_service.py` 四阶段 Map-Reduce（候选 → 引文标注 → 写页 → 收链）。
Wiki 页面不入 ES 检索。
```

## Directory Guide

### `backend/src/features/knowledge_space/`

- `api/` — FastAPI 路由
- `models/` — SQLAlchemy ORM 模型
- `repository/` — 持久化查询
- `schemas/` — Pydantic schemas
- `services/` — 业务编排（管道入口、任务编排、检索、向量化、QG、成员权限、审计）
- `tasks/` — arq worker 任务定义与异常处理
- `prompts/` — Feature 专属 prompt 模板

### `backend/src/engines/document/`

- `pipeline/` — DocumentLoader / DocumentProcessor / DocumentRegistry（按文件类型路由 Reader）
- `splitters/` — chunk 切分器
- `converters/` — 文档格式转换器
- `media/` — audio / video / vlm / OCR 多模态处理（`media/image/` 仅占位，图片理解在 `media/vlm/`）
- `integrations/deepdoc/` — DeepDoc 集成（vendored，详见 `docs/deepdoc/deepdoc-integration.md`）

### `backend/src/shared/document/`

- `readers/` — 跨 feature 文档读取器
- `validation/` — 跨 feature 文件校验（FileValidator）

### `backend/src/shared/storage/`

- `client_factory/` — ES/MinIO/Redis 客户端工厂
- `elasticsearch_client.py` — ES 操作封装
- `minio_client.py` — MinIO 操作封装

## Pipeline Node Names（统一后）

| 节点 | 文本 | 音频 | 视频 |
|------|------|------|------|
| 解析/转换 | `parsed` | `transcription_done` | `frames_extracted` → `descriptions_generated` |
| 切分 | `split` | `split` | `split` |
| 向量化 | `embedded` | `embedded` | `embedded` |
| 问题生成 | `question_generation` | `question_generation` | `question_generation` |
| 索引 | `indexed` | `indexed` | `indexed` |

后四个节点（split/embedded/question_generation/indexed）三模态统一由 `run_post_parse_tail`（`services/pipeline_steps.py`）管理。

## Import Guidance

- `novamind.features.knowledge_space.services...` — 业务编排
- `novamind.engines.document...` — 解析管道、切分器、媒体处理、DeepDoc
- `novamind.shared.document.readers...` — 跨 feature 读取器
- `novamind.shared.storage...` — 存储客户端
- `novamind.shared.utils...` — 仅通用工具
