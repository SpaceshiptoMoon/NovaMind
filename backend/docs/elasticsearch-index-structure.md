# Elasticsearch 索引结构

Mapping 权威源码: `backend/src/shared/storage/index_schema.py`（`DefaultIndexSchema.build_create_body`，由 `elasticsearch_client.py` 消费）

## 索引命名

每个知识空间独立索引: `space_{space_id}` (如 `space_1`)

## 完整字段定义

以下清单与 `index_schema.py` 的 mapping 声明一一对应（2026-11-18 对账）。

### 顶级字段（所有空间共有）

| 字段 | ES 类型 | 说明 |
|------|---------|------|
| `space_id` | long | 所属知识空间 ID |
| `kb_id` | long | 所属知识库 ID |
| `document_id` | long | 所属文档 ID |
| `chunk_id` | keyword | 分块唯一标识 (同时作为 `_id`) |
| `chunk_index` | integer | 分块序号 (文档内排序) |
| `content` | text (分词) | 分块正文内容，使用 standard 或 ik 分词器 |
| `embedding` | dense_vector (cosine) | 内容向量，维度由 embedding_dim 决定 (默认 1024) |
| `questions` | text (分词) | 假设问题文本 (自动生成的检索增强问题) |
| `question_embeddings` | nested → vector (dense_vector, cosine) | 假设问题的向量，每个问题独立向量 |
| `chunk_type` | keyword | 分块类型（text / image / video / audio / wiki_page 等，随模态与 wiki 同步扩展） |
| `lifecycle_status` | keyword | 文档生命周期（kb-ops）：chunk 级冗余文档状态，检索侧排除 superseded / archived；存量 chunk 无此字段视为可召回，零回填 |
| `image_url` | keyword | 图片 URL |
| `media_url` | keyword | 音 / 视频原文 URL（预签名后供前端播放） |
| `metadata` | object | 模态相关元数据，子字段见下表 |
| `file_info.filename` | keyword | 文件名 |
| `file_info.file_type` | keyword | 文件类型 (pdf、docx 等) |
| `created_at` | date | 创建时间 |
| `updated_at` | date | 更新时间 |

### metadata 子字段（显式声明的 28 个）

| 子字段 | ES 类型 | 说明 |
|--------|---------|------|
| `page_number` | integer | 页码 |
| `section_title` | text | 章节标题 |
| `char_start` / `char_end` | integer | 原文字符位置区间 |
| `content_hash` | keyword | 内容哈希 (去重用) |
| `wiki_slug` / `wiki_title` / `wiki_page_type` | keyword | wiki 页同步（chunk_type=wiki_page）：slug 过滤/回链、标题、页型 |
| `start_time` / `end_time` / `duration` | float | 音视频时间轴（秒） |
| `speaker_id` | keyword | ASR 说话人分离 ID |
| `confidence` | float | ASR 转写置信度（0~1，sigmoid(avg_logprob) 聚合） |
| `frame_paths` | keyword | 视频帧图路径列表（预签名后成 frame_urls） |
| `frame_indices` | integer | 帧序号列表 |
| `doc_tags` | text + .keyword 子字段 | 用户自定义标签（文档级打标 chunk 冗余；查询/聚合走 .keyword） |
| `chunk_pages` | integer | 引用溯源页码列表（tagged_rechunk 产物） |
| `chunk_entry_source_ids` / `chunk_entry_kinds` | keyword | 引用溯源 source_id / 条目类型列表 |
| `chunk_entry_count` | integer | 引用溯源条目数 |
| `figure_image_links` | nested（artifact_id / minio_object_name / image_url / page / caption） | PDF figure 图片链接 |
| `figure_image_count` | integer | figure 图片数 |
| `chunk_role` | keyword | 句窗口/父子分块角色（parent / child / anchor 等） |
| `parent_chunk_id` | keyword | 父子分块的父 chunk 引用 |
| `expansion_type` / `expansion_window_size` | keyword / integer | 句窗口扩展语义 |
| `content_type` | keyword | 内容类型标记 |
| `section_anchor_chunk_id` | keyword | 章节锚点 chunk 引用 |

未显式声明的 metadata 键由 ES 动态映射兜底（写侧控制键集，避免映射漂移）。

## 9 种检索模式 (search_by_mode)

| 模式 | 算法 | 搜索字段 |
|------|------|---------|
| `content_bm25` | BM25 | `content` |
| `content_vector` | KNN 向量 | `embedding` |
| `content_hybrid` | RRF 融合 | `content` + `embedding` |
| `question_bm25` | BM25 | `questions` |
| `question_vector` | KNN 向量 (nested) | `question_embeddings.vector` |
| `question_hybrid` | RRF 融合 | `questions` + `question_embeddings.vector` |
| `all_bm25` | BM25 加权 | `content` + `questions` |
| `all_vector` | RRF 融合 | `embedding` + `question_embeddings.vector` |
| `all_hybrid` | 4 路 RRF 全融合 | 全部 4 个字段 |

## 索引重建

embedding 配置变更导致维度变化时，会删除旧索引重建 (`space_service.py:751-765`)。