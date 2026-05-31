# Elasticsearch 文档结构

## 索引设计

### 索引命名

每个知识空间对应一个 ES 索引：`knowledge_space_{space_id}`

### 知识库隔离

同一空间内的所有知识库共享索引，通过 `kb_id` 字段（`term` 过滤）区分：

- **写入时**：每个 chunk 文档携带 `kb_id` 字段
- **检索时**：通过 `{"term": {"kb_id": kb_id}}` 过滤，只返回目标知识库的数据
- **跨知识库检索**：不传 `kb_id` 时搜索整个空间的所有知识库数据

---

## Document JSON 示例

```json
{
  "space_id": 1,
  "kb_id": 3,
  "document_id": 42,
  "chunk_id": "doc_42_chunk_5",
  "chunk_index": 5,
  "content": "FastAPI 是一个高性能的 Python Web 框架，支持异步编程...",
  "embedding": [0.0123, -0.0456, 0.0789, ...],
  "questions": [
    "FastAPI 框架的主要特点是什么？",
    "如何使用 FastAPI 定义一个 REST API 接口？"
  ],
  "question_embeddings": [
    { "vector": [0.0234, -0.0567, ...] },
    { "vector": [0.0345, -0.0678, ...] }
  ],
  "metadata": {
    "page_number": 5,
    "section_title": "快速入门",
    "char_start": 1200,
    "char_end": 1580,
    "content_hash": "a1b2c3d4e5f6"
  },
  "file_info": {
    "filename": "fastapi_guide.pdf",
    "file_type": ".pdf"
  },
  "created_at": "2026-04-22T10:30:00",
  "updated_at": "2026-04-22T10:30:00"
}
```

---

## 索引 Mapping

```json
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 0
  },
  "mappings": {
    "properties": {
      "space_id": { "type": "long" },
      "kb_id": { "type": "long" },
      "document_id": { "type": "long" },
      "chunk_id": { "type": "keyword" },
      "chunk_index": { "type": "integer" },
      "content": {
        "type": "text",
        "analyzer": "ik_max_word",
        "search_analyzer": "ik_smart"
      },
      "embedding": {
        "type": "dense_vector",
        "dims": 1024,
        "index": true,
        "similarity": "cosine"
      },
      "questions": {
        "type": "text",
        "analyzer": "ik_max_word",
        "search_analyzer": "ik_smart"
      },
      "question_embeddings": {
        "type": "nested",
        "properties": {
          "vector": {
            "type": "dense_vector",
            "dims": 1024,
            "index": true,
            "similarity": "cosine"
          }
        }
      },
      "metadata": {
        "properties": {
          "page_number": { "type": "integer" },
          "section_title": { "type": "text" },
          "char_start": { "type": "integer" },
          "char_end": { "type": "integer" },
          "content_hash": { "type": "keyword" }
        }
      },
      "file_info": {
        "properties": {
          "filename": { "type": "keyword" },
          "file_type": { "type": "keyword" }
        }
      },
      "created_at": { "type": "date" },
      "updated_at": { "type": "date" }
    }
  }
}
```

> `dims` 和 `analyzer` 的实际值由空间 Embedding 配置和用户配置决定。

---

## 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `space_id` | long | 所属空间 ID（索引级隔离） |
| `kb_id` | long | 所属知识库 ID（term 过滤隔离） |
| `document_id` | long | 所属文档 ID |
| `chunk_id` | keyword | 分块唯一标识（格式：`doc_{document_id}_chunk_{index}`） |
| `chunk_index` | integer | 分块序号（从 0 开始） |
| `content` | text | 分块原文，用于 BM25 全文检索 |
| `embedding` | dense_vector | 内容向量，用于向量检索 |
| `questions` | text | 假设性问题列表，用于问题全文检索 |
| `question_embeddings` | nested → dense_vector | 问题向量列表，用于问题向量检索 |
| `metadata` | object | 元数据（页码、章节标题、字符位置、内容哈希） |
| `file_info` | object | 文件信息（原始文件名、文件类型） |
| `created_at` | date | 创建时间 |
| `updated_at` | date | 更新时间 |

---

## 检索模式与字段对应

| 检索模式 | 搜索字段 | 说明 |
|---------|---------|------|
| `content_bm25` | `content` | 内容全文检索 |
| `content_vector` | `embedding` | 内容向量检索 |
| `content_hybrid` | `content` + `embedding` | 内容混合检索（BM25 + 向量） |
| `question_bm25` | `questions` | 问题全文检索 |
| `question_vector` | `question_embeddings.vector` | 问题向量检索 |
| `question_hybrid` | `questions` + `question_embeddings.vector` | 问题混合检索 |
| `all_bm25` | `content` + `questions` | 全字段全文检索 |
| `all_vector` | `embedding` + `question_embeddings.vector` | 全字段向量检索 |
| `all_hybrid` | 全部 | 全字段全算法融合 |
