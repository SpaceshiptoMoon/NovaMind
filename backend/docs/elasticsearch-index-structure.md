# Elasticsearch 索引结构

源码: `backend/src/shared/storage/elasticsearch_client.py`

## 索引命名

每个知识空间独立索引: `space_{space_id}` (如 `space_1`)

## 完整字段定义

### 基础字段 (所有空间共有)

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
| `chunk_type` | keyword | 分块类型 ("text" / "image") |
| `image_url` | keyword | 图片 URL |
| `metadata.page_number` | integer | 页码 |
| `metadata.section_title` | text | 章节标题 |
| `metadata.char_start` | integer | 原文起始字符位置 |
| `metadata.char_end` | integer | 原文结束字符位置 |
| `metadata.content_hash` | keyword | 内容哈希 (去重用) |
| `file_info.filename` | keyword | 文件名 |
| `file_info.file_type` | keyword | 文件类型 (pdf、docx 等) |
| `created_at` | date | 创建时间 |
| `updated_at` | date | 更新时间 |

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

embedding 配置变更导致维度变化时，会删除旧索引重建 (`space_service.py:709-712`)。