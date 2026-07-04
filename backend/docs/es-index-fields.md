# Elasticsearch 知识空间索引字段定义

> 保存两份：**当前字段**（代码现状）vs **全模态扩展字段**（建议方案）
>
> 来源代码：
> - Mapping 定义：`backend/src/shared/storage/elasticsearch_client.py` — `create_index()`
> - 文本 chunk 写入：`backend/src/features/knowledge_space/services/document_service.py` — `_prepare_es_chunks_static()`
> - 图片 chunk 写入：`backend/src/features/knowledge_space/services/document_service.py` — `_process_image_document_static()`
> - 搜索模式：`backend/src/shared/storage/elasticsearch_client.py` — `search_by_mode()`

---

# 第一部分：当前字段（代码现状）

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

多模态空间额外增加（第 178-184 行）：

```python
if multimodal_dim:
    properties["image_embedding"] = {  # dense_vector, cosine
        "dims": multimodal_dim,
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
image_embedding       ❌ 不写入
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
image_embedding       ✅  第 1158 行（多模态模型生成）
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

### 未注册到 `search_by_mode()` 的 2 种模式（独立端点）

| 模式 | 搜索字段 | 方法 | 调用端点 |
|------|---------|------|---------|
| `image_vector` | `image_embedding` | `image_vector_search()` | `/multimodal-search` |
| `text_to_image` | `embedding` + `image_embedding` | `image_hybrid_vector_search()` + RRF | `/multimodal-search` |

---

# 第二部分：全模态扩展字段（建议方案）

## 一、设计原则

1. **能复用的不复用**：相同向量空间的数据用同一字段（视频帧复用 `image_embedding`）
2. **该新增的新增**：不同向量空间必须独立（声学 `audio_embedding` 必须新增）
3. **不搞过度设计**：只加真正需要的，不预设未来

### 向量空间决策依据

```
CLIP/SigLIP 向量空间（视觉）：
  文本描述 ← 对齐 → 图片
                      ↕
                 视频关键帧  ← 复用 image_embedding

CLAP/WavRAG 向量空间（声学，完全不同）：
  语音转写文本 ← 对齐 → 原始音频波形
                         ↑
                  必须新增 audio_embedding
```

## 二、字段变更清单

### 保留不变（12 个）

| 字段 | 说明 |
|------|------|
| `space_id` | 空间 ID |
| `kb_id` | 知识库 ID |
| `document_id` | 文档 ID |
| `chunk_id` | 分块 ID |
| `chunk_index` | 分块序号 |
| `content` | 文本内容（复用：文本 / VLM 图片描述 / ASR 语音转写 / 视频场景描述） |
| `embedding` | 文本向量（复用：以上所有文本的向量） |
| `questions` | 假设问题 |
| `question_embeddings` | 假设问题向量 |
| `chunk_type` | chunk 子类型，扩展值范围：`"text"`\|`"image"`\|`"video"`\|`"audio"` |
| `file_info` | 文件信息（filename, file_type）— 已有但文本 chunk 实际未写入，全模态时统一启用 |
| `image_embedding` | 视觉向量（原有仅多模态空间，扩展为图片+视频关键帧通用） |

### 微调（2 处）

| 原字段 | 改为 | 原因 |
|--------|------|------|
| `image_url` → `media_url` | `media_url`（keyword） | 不再只是图片，视频/音频文件路径也存这里 |
| `metadata` 扩展 | 增加 `start_time`/`end_time`/`duration`/`speaker_id` | 音视频需要时间戳和说话人信息 |

### 新增（3 个）

| 字段 | 类型 | 用途 | 为什么必须新增 |
|------|------|------|--------------|
| `modal_type` | **keyword** | 管线路由标记：`"text"`\|`"image"`\|`"video"`\|`"audio"` | `chunk_type` 是数据块子类型，`modal_type` 是顶层模态标记，两者语义不同 |
| `audio_embedding` | **dense_vector**（cosine） | 音频的声学向量（CLAP/WavRAG） | 声学向量空间与视觉/文本完全独立，不能混用 |
| `scene_index` | **integer** | 视频场景/镜头序号 | 用于视频按场景/镜头分片 |

### 按需启用（2 个，已有 mapping 但不写入）

| 字段 | 说明 |
|------|------|
| `created_at` | 已在 mapping 中，文本/图片 chunk 均未写入。全模态时统一写入 |
| `updated_at` | 同上 |

## 三、最终 Mapping（建议）

```python
properties = {
    # ── 保留字段 ──
    "space_id":             {"type": "long"},
    "kb_id":                {"type": "long"},
    "document_id":          {"type": "long"},
    "chunk_id":             {"type": "keyword"},
    "chunk_index":          {"type": "integer"},
    "content":              {"type": "text", ...},         # 文本 / VLM描述 / ASR转写 / 场景描述
    "embedding":            {"type": "dense_vector", ...}, # 文本向量
    "questions":            {"type": "text", ...},
    "question_embeddings":  {"type": "nested", ...},
    "chunk_type":           {"type": "keyword"},           # "text"|"image"|"video"|"audio"
    "file_info": {
        "filename":         {"type": "keyword"},
        "file_type":        {"type": "keyword"},
    },
    "image_embedding":      {"type": "dense_vector", ...}, # 视觉向量（图片+视频关键帧）

    # ── 微调字段 ──
    "media_url":            {"type": "keyword"},           # 原 image_url 升级
    "metadata": {
        "page_number":      {"type": "integer"},
        "section_title":    {"type": "text"},
        "char_start":       {"type": "integer"},
        "char_end":         {"type": "integer"},
        "content_hash":     {"type": "keyword"},
        "start_time":       {"type": "float"},             # 新增：音视频起始秒
        "end_time":         {"type": "float"},             # 新增：音视频结束秒
        "duration":         {"type": "float"},             # 新增：总时长
        "speaker_id":       {"type": "keyword"},           # 新增：说话人
    },

    # ── 新增字段 ──
    "modal_type":           {"type": "keyword"},           # "text"|"image"|"video"|"audio"
    "audio_embedding":      {"type": "dense_vector", ...}, # 声学向量（仅音频）
    "scene_index":          {"type": "integer"},           # 视频场景序号

    # ── 启用已有字段 ──
    "created_at":           {"type": "date"},
    "updated_at":           {"type": "date"},
}
```

## 四、搜索模式映射（扩展后）

| 模态 | 搜索模式 | 搜索字段 | 算法 |
|------|---------|---------|------|
| 文本 | `content_bm25` | `content` | BM25 |
| 文本 | `content_vector` | `embedding` | KNN |
| 文本 | `content_hybrid` | `content` + `embedding` | RRF |
| 文本 | `question_bm25` | `questions` | BM25 |
| 文本 | `question_vector` | `question_embeddings.vector` | KNN |
| 文本 | `question_hybrid` | `questions` + `q_embeddings` | RRF |
| 文本 | `all_bm25` | `content` + `questions` | BM25 |
| 文本 | `all_vector` | `embedding` + `q_embeddings` | RRF |
| 文本 | `all_hybrid` | 全部 4 字段 | RRF |
| 图片 | `image_vector` | `image_embedding` | KNN + `modal_type="image"` |
| 图片 | `text_to_image` | `embedding` + `image_embedding` | RRF + `modal_type="image"` |
| 视频 | `video_vector` | `image_embedding` | KNN + `modal_type="video"` |
| 视频 | `video_hybrid` | `content` + `image_embedding` | RRF + `modal_type="video"` |
| 音频 | `audio_vector` | `audio_embedding` | KNN + `modal_type="audio"` |
| 音频 | `audio_hybrid` | `content` + `audio_embedding` | RRF + `modal_type="audio"` |
| 全模态 | `all_modal` | 全部向量字段 | RRF 全融合（按 modal_type 按需过滤） |

## 五、变更总结

| 操作 | 数量 | 字段 |
|------|------|------|
| 保留 | 12 | space_id, kb_id, document_id, chunk_id, chunk_index, content, embedding, questions, question_embeddings, chunk_type, file_info, image_embedding |
| 微调 | 2 处 | `image_url`→`media_url`, `metadata` 加时间戳/说话人 |
| **新增** | **3** | **`modal_type`**, **`audio_embedding`**, **`scene_index`** |
| 按需启用 | 2 | created_at, updated_at（已有 mapping 但未写） |
