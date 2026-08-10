# Knowledge Architecture Navigation

## Purpose

This document describes the current canonical backend knowledge-base structure.

## Final Structure

### Feature Layer

- `backend/src/features/knowledge_space/`
  - 所有权：API、业务编排、持久化、schemas、权限、管道、切分器、转换器、媒体处理、DeepDoc 集成

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

三模态（文本/音频/视频）管道形态：
  解析(转换器) → persist_parsed_text(MD → MinIO)
               → _run_post_parse_tail(切分 → 向量化 → QG → 索引)
                   ├── _split_md_text / prechunked
                   ├── _build_es_chunks（统一 ES chunk 构造器）
                   ├── _generate_embeddings_static
                   ├── _generate_questions_for_chunks_static（由 pipeline_config 控制）
                   └── _get_es_client_static → bulk_index_chunks

图片管道独立，不走共享后置尾（单 chunk、无 QG、es_chunk 形状不同）。
```

## Directory Guide

### `backend/src/features/knowledge_space/`

- `api/` — FastAPI 路由
- `models/` — SQLAlchemy ORM 模型
- `repository/` — 持久化查询
- `schemas/` — Pydantic schemas
- `services/` — 业务编排（包含管道入口与共享后置尾）
- `prompts/` — Feature 专属 prompt 模板
- `pipeline/` — 文档解析管道（DocumentLoader/DocumentProcessor/DocumentRegistry）
- `splitters/` — 切分器（recursive/semantic/fixed/markdown）
- `converters/` — 文档格式转换器
- `media/` — 音视频/图片多模态处理
- `integrations/deepdoc/` — DeepDoc 集成（自包含）

### `backend/src/shared/document/`

- `readers/` — 跨 feature 文档读取器
- `validation/` — 跨 feature 文件校验

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

后四个节点（split/embedded/question_generation/indexed）三模态统一由 `_run_post_parse_tail` 管理。

## Import Guidance

- `novamind.features.knowledge_space.services...` — 业务编排
- `novamind.shared.document.readers...` — 跨 feature 读取器
- `novamind.shared.storage...` — 存储客户端
- `novamind.shared.utils...` — 仅通用工具
