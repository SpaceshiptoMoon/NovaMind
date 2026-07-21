# 知识库后端组件架构（知识空间模块）

> 最后更新：2026-07-21

---

## 一、目录结构

```
backend/src/features/knowledge_space/
├── api/                          # 路由层
│   ├── space_router.py           # 空间 CRUD + 配置（/api/v1/spaces）
│   ├── knowledge_base_routes.py  # 知识库 CRUD + 配置
│   ├── document_routes.py        # 文档上传/处理/下载
│   ├── search_routes.py          # 文本搜索
│   ├── member_routes.py          # 空间成员管理
│   ├── dependencies.py           # DI 工厂 + 权限校验
│   ├── exceptions.py             # 28 种异常定义
│   └── startup.py                # 模块初始化 + 异常注册
├── models/                       # ORM 模型
│   ├── knowledge_space.py        # KnowledgeSpace（主模型）
│   ├── knowledge_base.py         # KnowledgeBase（子模型）
│   ├── document.py               # Document（文档）
│   ├── space_member.py           # SpaceMember（成员关系）
│   └── space_audit_log.py        # SpaceAuditLog（审计日志）
├── schemas/                      # Pydantic v2 Schema
│   ├── space_schema.py           # SpaceConfig / SpaceCreate / SpaceUpdate
│   ├── knowledge_base_schema.py  # KBCreate / KBUpdate
│   ├── document_schema.py        # DocumentUpload / DocumentResponse / Chunk
│   ├── search_schema.py          # SearchRequest
│   └── member_schema.py          # Member / Invite
├── services/                     # 业务逻辑
│   ├── space_service.py          # 空间创建/配置/ES索引管理
│   ├── knowledge_base_service.py # 知识库 CRUD
│   ├── document_service.py       # 文档处理管道（核心）
│   ├── search_service.py         # 检索服务（9 种模式）
│   ├── embedding_service.py      # 向量化服务（Redis缓存）
│   ├── question_generation_service.py  # 假设问题生成
│   ├── member_service.py         # 成员管理
│   ├── permission_service.py     # RBAC 权限
│   └── audit_service.py          # 审计日志
└── repository/                   # 数据访问
    ├── space_repository.py       # 空间（Redis 缓存）
    ├── knowledge_base_repository.py  # 知识库
    ├── document_repository.py    # 文档（Redis 缓存）
    ├── member_repository.py      # 成员
    └── audit_repository.py       # 审计
```

### 外部依赖

```
backend/src/shared/
├── storage/
│   └── elasticsearch_client.py   # ES 客户端（索引管理 + 9种搜索 + RRF）
│   └── minio_client.py           # MinIO 文件存储
├── cache/
│   ├── redis_client.py           # Redis 客户端
│   └── cache_service.py          # 缓存服务
├── ai_models/
│   ├── embedding/                # Embedding 客户端工厂
│   ├── llm/                      # LLM 客户端
│   └── rerank/                   # Rerank 客户端
├── mq/
│   ├── worker.py                 # arq Worker（文档处理任务）
│   └── task_tracker.py           # 任务追踪
├── utils/
│   ├── document_readers/         # 文档解析器（PDF/DOCX/HTML/MD/TXT）
│   │   └── splitters/            # 切片器（recursive/fixed/markdown/semantic）
│   ├── file_validator.py         # 文件类型校验（魔数+MIME）
│   └── crypto.py                 # AES 加密
└── prompts/
    └── templates.py              # PromptTemplate 枚举
```

---

## 二、核心数据流：文档上传→处理→检索

### 2.1 文档上传流程

```
前端 POST /api/v1/spaces/{id}/knowledge-bases/{kb_id}/documents
  → document_routes.py: upload_document()
    → 1. 权限校验（validate_space_editor）
    → 2. 文件类型校验（file_validator.py + ALLOWED_FILE_EXTENSIONS）
    → 3. 空间类型校验
    → 4. MinIO 上传 → 写入 Document 记录（status=UPLOADED）
    → 5. arq 入队：enqueue_process_document(document_id, kb_id, space_id)
```

### 2.2 文档处理管道

```
arq Worker → process_document_task()
  → DocumentService.execute_document_pipeline()
    │
    ├─ 文本文件分支（pdf/docx/txt/md/...）：
    │   → DocumentProcessor 解析（按文件类型选 Reader）
    │   → Splitter 切片
    │   → EmbeddingService 向量化（Redis 缓存，48h TTL）
    │   → QuestionGenerationService 假设问题生成（可选）
    │   → ElasticsearchClient.bulk_index_chunks() 批量索引
    │
    ├─ 图片文件分支（jpg/png/gif/webp）：
    │   → _process_image_document_static()
    │   → VLM 描述生成（可选，需开启 vlm_description_enabled）
    │   → 构建 image chunk → ES 索引
    │
    ├─ 视频文件分支（mp4/mov/avi/mkv/webm）：
    │   → process_video_document()
    │   → 关键帧提取 → VLM 描述 → 文本向量化 → ES 索引
    │
    └─ 音频文件分支（mp3/wav/flac/aac/ogg/m4a）：
        → process_audio_document()
        → ASR 转写 → 文本切片 → 向量化 → ES 索引
```

### 2.3 检索流程

```
前端 POST /api/v1/spaces/{id}/knowledge-bases/{kb_id}/search
  → search_routes.py → SearchService.search()
    → 1. 权限校验 + 知识库验证
    → 2. 检查缓存（Redis，key: search:{kb_id}:{mode}:{hash}）
    → 3. 查询改写（HyDE / Sub Query—可选）
    → 4. 生成查询向量（EmbeddingService）
    → 5. es_client.search_by_mode() 路由到对应搜索模式
    → 6. _enrich_results() 补充结果详情
    → 7. _normalize_scores() Min-Max 归一化
    → 8. score_threshold 过滤
    → 9. Rerank 重排序（可选）
    → 10. 缓存结果（可选）
    → 11. LLM 回答生成（可选）
```

---

## 三、关键配置点

### 3.1 空间级别配置（`SpaceConfig` / `space_schema.py:39`）

| 字段 | 类型 | 说明 | 扩展备注 |
|------|------|------|----------|
| `space_type` | `string[]` | 空间支持的模态列表 | 支持 `"text"`, `"image"`, `"video"`, `"audio"` |
| `embedding` | `SpaceEmbeddingConfig` | 文本 Embedding 模型 | 所有模态共用文本向量化 |
| `llm` | `SpaceLLMConfig` | 默认 LLM 配置 | 问题生成、查询改写、摘要 |
| `asr` | `SpaceASRConfig` | ASR 配置 | 音频转文字 |
| `vlm` | `SpaceVLMConfig` | VLM 配置 | 图片/视频帧描述 |

### 3.2 知识库级别配置（`KnowledgeBase` 的 `config` JSON）

| 子配置 | 说明 | 扩展备注 |
|--------|------|----------|
| `splitting` | 切片策略（strategy/chunk_size/overlap） | 视频需新增场景切割 |
| `parsing` | 解析配置（PDF策略、VLM策略、ASR参数等） | 音视频各有独立参数 |
| `question_generation` | 假设问题生成（enabled/model/batch_size） | 所有模态可复用 |

### 3.3 模型类型映射

```python
_MODEL_TYPE_STR = {
    "embedding": "embedding",
    "llm": "llm",
    "rerank": "rerank",
    "vlm": "vlm",
    "asr": "asr",
}
```

---

## 四、各层需要修改的组件（全模态扩展清单）

### 4.1 Models — 需要修改

| 文件 | 修改内容 |
|------|---------|
| `knowledge_space.py` | `space_type` 扩展支持 `"video"`/`"audio"`；音视频相关配置属性 |
| `knowledge_base.py` | `parsing` 配置扩展音视频处理参数 |
| `document.py` | 文件类型扩展（mp4/mp3/wav 等）；`file_type` 兼容音视频格式 |

### 4.2 Schemas — 需要修改

| 文件 | 修改内容 |
|------|---------|
| `space_schema.py` | `SpaceConfig.space_type` 扩展模态枚举；新增音视频配置字段 |
| `search_schema.py` | 新增音视频搜索结果字段（`audio_url`、`video_url`、`start_time`、`duration` 等） |
| `document_schema.py` | 新增音视频文档响应类型；`ChunkResponse` 扩展时间戳/模态信息 |

### 4.3 Services — 核心修改

| 文件 | 修改内容 |
|------|---------|
| **`document_service.py`** | **核心管道扩展**：新增音视频处理分支；`ALLOWED_FILE_TYPES` 扩展；空间类型校验逻辑重写 |
| **`search_service.py`** | **检索统一**：`search_by_mode()` 注册全模态模式；全模态缓存/rerank/LLM回答；`_enrich_results` 返回音视频字段 |
| `space_service.py` | 模型类型映射扩展；`_build_es_create_kwargs` 传递音视频维度；空间类型互斥校验需重写 |
| `embedding_service.py` | 新增音视频向量化缓存（格式对齐 `emb:{model}:{modal_type}:{hash}`） |
| `question_generation_service.py` | 图片/视频/音频可考虑复用或跳过 |

### 4.4 API Routes — 需要修改

| 文件 | 修改内容 |
|------|---------|
| `search_routes.py` | 全模态搜索端点整合；`search/modes` 返回全模态模式列表 |
| `document_routes.py` | `ALLOWED_FILE_EXTENSIONS` 扩展音视频格式；最大文件大小可放宽 |
| `space_router.py` | 空间类型变更校验需适配更多模态 |

### 4.5 ES Client — 核心修改

| 文件 | 修改内容 |
|------|---------|
| `elasticsearch_client.py` | `create_index()` 新增 `modal_type` 字段；`search_by_mode()` 注册全模态模式 |

### 4.6 Shared 层 — 需要新增/修改

| 文件 | 修改内容 |
|------|---------|
| `file_validator.py` | `EXTENSION_TO_MIME` 扩展音视频类型；`MAGIC_SIGNATURES` 新增音视频魔数 |
| `ai_models/` 模型类型 | `ModelConfigService` 需支持音频嵌入模型类型 |
| `utils/document_readers/` | 新增音频/视频 Reader |
| `utils/document_readers/splitters/` | 新增视频场景切割器、音频切片器 |
| `mq/worker.py` | 文档处理任务区分音视频路径 |

### 4.7 无需修改的组件

| 组件 | 理由 |
|------|------|
| `member_service.py` | 成员管理与模态无关 |
| `permission_service.py` | RBAC 不关心数据类型 |
| `audit_service.py` | 审计日志与模态无关 |
| `minio_client.py` | 文件存储已通用，任何文件类型都可存 |
| `cache_service.py` | 缓存基础设施与模态无关 |
| `prompts/templates.py` | 需新增模板但基础设施不改 |
| `core/*` | 核心基础设施不变 |

---

## 五、文件大小与类型限制现状

| 配置 | 当前值 | 来源 |
|------|--------|------|
| 允许上传的文件类型 | `pdf,docx,doc,txt,md,csv,xlsx,xls,pptx,ppt,html,json,jpg,jpeg,png,gif,webp,mp4,mov,avi,mkv,webm,mp3,wav,flac,aac,ogg,m4a` | `document_routes.py:60` |
| 最大文件大小 | 100MB（视频 500MB） | `document_routes.py:57` |
| 图片文件类型 | `jpg,jpeg,png,gif,webp` | `document_service.py:91` |
| 批量上传最大数 | 20 个 | `document_routes.py:63` |