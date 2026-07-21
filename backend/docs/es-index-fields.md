# Elasticsearch 知识空间索引字段定义

> 来源代码：
> - Mapping 定义：`backend/src/shared/storage/elasticsearch_client.py` — `create_index()`
> - 文本 chunk 写入：`backend/src/features/knowledge_space/services/document_service.py` — `_prepare_es_chunks_static()`
> - 图片 chunk 写入：`backend/src/features/knowledge_space/services/document_service.py` — `_process_image_document_static()`
> - 搜索模式：`backend/src/shared/storage/elasticsearch_client.py` — `search_by_mode()`

---

# 当前字段（代码现状）

## 一、Mapping 定义（`es_client.py:124-184`）

创建索引时所有空间共有的 15 个字段：

```python
properties = {
    "space_id":             {"type": "long"},
    "kb_id":                {"type": "long"},
    "document_id":          {"type": "long"},
    "chunk_id":             {"type": "keyword"},          # 同时作为 doc _id
    "chunk_index":          {"type": "integer"},
    "content":              {"type": "text", ...},         # 可配 analyzer/ik 分词
    "embedding":            {"type": "dense_vector", ...}, # dims=1024默认, cosine
    "questions":            {"type": "text", ...},         # 假设问题
    "question_embeddings":  {"type": "nested", ...},       # {vector: dense_vector}
    "chunk_type":           {"type": "keyword"},           # "text" | "image"
    "image_url":            {"type": "keyword"},
    "metadata": {
        "page_number":      {"type": "integer"},
        "section_title":    {"type": "text"},
        "char_start":       {"type": "integer"},
        "char_end":         {"type": "integer"},
        "content_hash":     {"type": "keyword"},
    },
    "file_info": {
        "filename":         {"type": "keyword"},
        "file_type":        {"type": "keyword"},
    },
    "created_at":           {"type": "date"},
    "updated_at":           {"type": "date"},
}
```

## 二、实际写入的字段（Mapping 的子集）

### 文本 chunk — 最终写入 10 个字段

构建于 `document_service.py:1230-1244`，向量化后追加 `:427`：

```
space_id              ✅  第 1233 行
kb_id                 ✅  第 1234 行
document_id           ✅  第 1235 行
chunk_id              ✅  第 1236 行（格式: {doc_id}_{i}）
chunk_index           ✅  第 1237 行（从 0 递增）
content               ✅  第 1238 行（切片文本）
chunk_type            ✅  第 1239 行（固定 "text"）
questions             ✅  第 1240 行（初始 []，问题生成后填充）
question_embeddings   ✅  第 1241 行（初始 []，问题生成后填充）
embedding             ✅  第 427 行（向量化后写入）
──────────────────────────────────────────
image_url             ❌ 不写入
metadata.*            ❌ 不写入（mapping 定义了 page_number/section_title 等但从未写）
file_info.*           ❌ 不写入（mapping 定义了 filename/file_type 但从未写）
created_at            ❌ 不写入
updated_at            ❌ 不写入
```

### 图片 chunk — 最终写入 9~11 个字段

构建于 `document_service.py:1151-1175`：

```
space_id              ✅  第 1152 行
kb_id                 ✅  第 1153 行
document_id           ✅  第 1154 行
chunk_id              ✅  第 1155 行（固定格式 {doc_id}_0）
chunk_index           ✅  第 1156 行（固定 0）
chunk_type            ✅  第 1157 行（固定 "image"）
image_url             ✅  第 1159 行（MinIO 路径）
file_info.filename    ✅  第 1161 行
file_info.file_type   ✅  第 1162 行
metadata.content_hash ✅  第 1165 行（document.file_hash）
content               ⚠️  第 1171 行（仅 VLM 开启且生成了描述时写入）
embedding             ⚠️  第 1175 行（仅 VLM 开启且生成了描述文本向量时写入）
──────────────────────────────────────────
questions             ❌ 不写入
question_embeddings   ❌ 不写入
created_at            ❌ 不写入
updated_at            ❌ 不写入
```

## 三、搜索模式与字段对应

### 已注册到 `search_by_mode()` 的 9 种模式（`es_client.py:799-841`）

| 模式 | 搜索字段 | 算法 |
|------|---------|------|
| `content_bm25` | `content` | BM25 |
| `content_vector` | `embedding` | KNN |
| `content_hybrid` | `content` + `embedding` | RRF 融合 |
| `question_bm25` | `questions` | BM25 |
| `question_vector` | `question_embeddings.vector` | KNN（nested） |
| `question_hybrid` | `questions` + `question_embeddings.vector` | RRF 融合 |
| `all_bm25` | `content` + `questions` | BM25 加权 |
| `all_vector` | `embedding` + `question_embeddings.vector` | RRF 融合 |
| `all_hybrid` | 全部 4 个字段 | 4 路 RRF 全融合 |