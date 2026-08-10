# Elasticsearch 知识空间索引字段定义

> 来源代码：
> - Mapping 定义：`backend/src/shared/storage/elasticsearch_client.py` — `create_index()`
> - 文本/音频/视频 chunk 写入：`backend/src/features/knowledge_space/services/document_pipeline.py` — `_build_es_chunks()`（统一构造器，三模态共用），`_prepare_es_chunks_static()`（旧 shim，保留兼容）
> - 图片 chunk 写入：`backend/src/features/knowledge_space/services/document_pipeline.py` — `_process_image_document_static()`
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

构建于 `document_pipeline.py` `_build_es_chunks()`（文本分支），`questions`/`question_embeddings` 在 `_run_post_parse_tail` 问题生成步骤填充，`embedding` 在向量化步骤追加：

```
space_id              ✅  第 1915 行
kb_id                 ✅  第 1916 行
document_id           ✅  第 1917 行
chunk_id              ✅  第 1918 行（格式: {doc_id}_{i}）
chunk_index           ✅  第 1919 行（从 0 递增）
content               ✅  第 1920 行（切片文本）
chunk_type            ✅  第 1921 行（固定 "text"）
questions             ✅  第 1928 行（初始 []，问题生成后填充）
question_embeddings   ✅  第 1929 行（初始 []，问题生成后填充）
embedding             ✅  第 2025 行（向量化后写入）
──────────────────────────────────────────
image_url             ❌ 不写入（文本分支仅在非文本时写 image_url，见 `_build_es_chunks:1932-1933`）
metadata.*            ❌ 不写入（mapping 定义了 page_number/section_title 等但从未写）
file_info.*           ❌ 不写入（mapping 定义了 filename/file_type 但从未写）
created_at            ❌ 不写入
updated_at            ❌ 不写入
```

### 图片 chunk — 最终写入 9~11 个字段

构建于 `document_pipeline.py` `_process_image_document_static()`：

```
space_id              ✅  第 1768 行
kb_id                 ✅  第 1769 行
document_id           ✅  第 1770 行
chunk_id              ✅  第 1771 行（固定格式 {doc_id}_0）
chunk_index           ✅  第 1772 行（固定 0）
chunk_type            ✅  第 1773 行（固定 "image"）
image_url             ✅  第 1776 行（MinIO 路径）
file_info.filename    ✅  第 1778 行
file_info.file_type   ✅  第 1779 行
metadata.content_hash ✅  第 1782 行（document.file_hash）
content               ⚠️  第 1774 行（仅 VLM 开启且生成了描述时写入）
embedding             ⚠️  第 1775 行（仅 VLM 开启且生成了描述文本向量时写入）
──────────────────────────────────────────
questions             ❌ 不写入
question_embeddings   ❌ 不写入
created_at            ❌ 不写入
updated_at            ❌ 不写入
```

### 音频/视频 chunk — 最终写入 13 个字段

构建于 `document_pipeline.py` `_build_es_chunks()`（媒体分支，由 `_run_post_parse_tail` 调用）。音频与视频共用同一构造路径，仅 `chunk_type`（`AUDIO`/`VIDEO`）与是否带 `frame_paths` 不同：

```
space_id              ✅  第 1915 行
kb_id                 ✅  第 1916 行
document_id           ✅  第 1917 行
chunk_id              ✅  第 1918 行（格式: {doc_id}_{i}）
chunk_index           ✅  第 1919 行（从 0 递增）
content               ✅  第 1920 行（切片文本：ASR 转写 / VLM 帧描述）
chunk_type            ✅  第 1921 行（"audio" | "video"）
media_url             ✅  第 1922 行（MinIO 对象名）
image_url             ✅  第 1933 行（== media_url，媒体分支写）
file_info.filename    ✅  第 1924 行
file_info.file_type   ✅  第 1925 行
metadata.content_hash ✅  第 1894 行（document.file_hash）
metadata.start_time   ✅  第 1906 行（音频分段时间戳 / 视频帧时间戳）
metadata.end_time     ✅  第 1907 行
metadata.frame_paths  ✅  第 1909 行（仅视频：按 chunk 的 frame_indices 映射 frame_paths）
questions             ✅  第 1928 行（初始 []，QG 开启时由 _run_post_parse_tail 填充 :2050）
question_embeddings   ✅  第 1929 行（初始 []，QG 开启时填充 :2051）
embedding             ✅  第 2025 行（向量化后写入，_run_post_parse_tail embedded 步骤）
created_at            ✅  第 1930 行（now_china().isoformat()）
──────────────────────────────────────────
updated_at            ❌ 不写入
```

> QG 由 `pipeline_config["question_generation"]["enabled"]` 控制，三模态统一经 `_run_post_parse_tail` 生成（见 `knowledge-architecture-navigation.md`）。QG 关闭时 `questions`/`question_embeddings` 保持 `[]`。

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