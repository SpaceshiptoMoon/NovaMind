# 知识库后端组件架构（知识空间模块）

> 最后更新：2026-09-18

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
│   ├── wiki_routes.py            # Wiki 只读/编辑/版本/回滚/图谱/lint API
│   └── startup.py                # 模块初始化 + 异常注册
├── models/                       # ORM 模型
│   ├── knowledge_space.py        # KnowledgeSpace（主模型）
│   ├── knowledge_base.py         # KnowledgeBase（子模型）
│   ├── document.py               # Document（文档）
│   ├── document_task.py          # DocumentTask（任务项）
│   ├── document_task_batch.py    # DocumentTaskBatch（批次头）
│   ├── document_task_item.py     # DocumentTaskItem（批次成员）
│   ├── space_member.py           # SpaceMember（成员关系）
│   ├── space_audit_log.py        # SpaceAuditLog（审计日志）
│   └── wiki.py                   # WikiPage / WikiPageRevision / WikiPageIssue / WikiIngestRecord
├── schemas/                      # Pydantic v2 Schema
│   ├── space_schema.py           # SpaceConfig / SpaceCreate / SpaceUpdate
│   ├── knowledge_base_schema.py  # KBCreate / KBUpdate
│   ├── document_schema.py        # DocumentUpload / DocumentResponse / Chunk
│   ├── search_schema.py          # SearchRequest
│   ├── document_task_schema.py   # 任务/批次 schema
│   ├── wiki_schema.py            # WikiPage / Revision / Issue / Graph 等 schema
│   └── member_schema.py          # Member / Invite
├── services/                     # 业务逻辑
│   ├── space_service.py          # 空间创建/配置/ES索引管理
│   ├── knowledge_base_service.py # 知识库 CRUD
│   ├── document_file_types.py    # 文件类型常量与模态映射（中立，三方共用）
│   ├── document_pipeline.py      # 文档处理管道执行（execute_document_pipeline + 助手群）
│   ├── document_upload_service.py # 文档上传校验 + MinIO 落库
│   ├── document_task_service.py  # 文档任务/批次编排（入队/取消/状态）
│   ├── document_query_service.py # 文档 CRUD/下载/级联删除
│   ├── search_service.py         # 检索服务（9 种模式）
│   ├── media_processing.py       # 音频/视频/图片多模态处理
│   ├── question_generation_service.py  # 假设问题生成
│   ├── pipeline_snapshots.py     # 解析管道指纹快照（断点续跑）
│   ├── wiki_ingest_service.py    # Wiki 四阶段生成管道（候选→引文→写页→收链）
│   ├── member_service.py         # 成员管理
│   ├── permission_service.py     # RBAC 权限
│   └── audit_service.py          # 审计日志
└── repository/                   # 数据访问
    ├── space_repository.py       # 空间（Redis 缓存）
    ├── knowledge_base_repository.py  # 知识库
    ├── document_repository.py    # 文档（Redis 缓存）
    ├── member_repository.py      # 成员
    ├── document_task_repository.py / document_task_batch_repository.py  # 任务与批次
    ├── wiki_repository.py        # WikiPage / Revision（快照、乐观锁、两级裁剪）
    ├── wiki_issue_repository.py  # WikiPageIssue
    └── audit_repository.py       # 审计
```

### 外部依赖

```
backend/src/
├── shared/
│   ├── storage/
│   │   ├── elasticsearch_client.py   # ES 客户端（索引管理 + 9种搜索 + RRF）
│   │   └── minio_client.py           # MinIO 文件存储
│   ├── cache/
│   │   ├── redis_client.py           # Redis 客户端
│   │   └── cache_service.py          # 缓存服务
│   ├── ai_models/
│   │   ├── embedding/                # Embedding 客户端工厂
│   │   ├── llm/                      # LLM 客户端
│   │   └── rerank/                   # Rerank 客户端
│   ├── mq/
│   │   ├── worker.py                 # arq Worker（文档处理任务）
│   │   └── task_tracker.py           # 任务追踪
│   ├── document/
│   │   ├── readers/                  # 跨 feature 文档读取器（PDF/DOCX/HTML/MD/TXT）
│   │   └── validation/               # 文件类型校验（魔数+MIME，FileValidator）
│   └── prompts/
│       └── templates.py              # PromptTemplate 枚举
└── engines/document/                 # 文档处理引擎（纯逻辑层）
    ├── pipeline/                     # DocumentLoader / DocumentProcessor / DocumentRegistry
    ├── splitters/                    # 切片器（recursive/fixed/markdown/semantic）
    ├── converters/                   # 文档格式转换器
    ├── media/                        # 音频 ASR / 视频抽帧 / VLM / OCR
    └── integrations/deepdoc/         # DeepDoc（vendored，自包含）
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
  → document_pipeline.execute_document_pipeline()（按文件类型路由）
    │
    ├─ 文本分支（pdf/docx/txt/md/...）：
    │   → DocumentProcessor 解析（按文件类型选 Reader，DeepDoc 结构化切块在内）
    │   → persist_parsed_text（解析 MD 全文 → MinIO）
    │   → _run_post_parse_tail（prechunked 优先，回退 _split_md_text）
    │
    ├─ 视频分支（mp4/mov/avi/mkv/webm）：
    │   → process_video_document()：关键帧提取 → VLM 帧描述（转换器）
    │   → persist_parsed_text（帧描述拼接 MD → MinIO）
    │   → _run_post_parse_tail（_split_md_text 切片，frame_paths 映射）
    │
    ├─ 音频分支（mp3/wav/flac/aac/ogg/m4a）：
    │   → process_audio_document()：ASR 转写（转换器）
    │   → persist_parsed_text（转写 MD → MinIO）
    │   → _run_post_parse_tail（_split_md_text 切片）
    │
    └─ 图片分支（jpg/png/gif/webp）：独立通路，不走共享后置尾
        → _process_image_document_static()
        → VLM 描述生成（可选，需开启 vlm_description_enabled）
        → 构建 image chunk → ES 索引

  _run_post_parse_tail（文本/音频/视频共用，节点名统一 split/embedded/question_generation/indexed）：
    split → _build_es_chunks → embedded（EmbeddingService，Redis 缓存 48h TTL）
            → question_generation（QuestionGenerationService，由 pipeline_config 控制）
            → indexed（ElasticsearchClient.bulk_index_chunks）

  注意：QG 现对三模态统一生效（原音频/视频分块不生成假设问题已修复）；图片分支单 chunk、无 QG。
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
| `question_generation` | 假设问题生成（enabled/model/batch_size） | 文本/音频/视频统一复用（经 `_run_post_parse_tail`）；图片分支无 QG |

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

## 四、历史扩展清单（全模态扩展，已于 2026-07 落地）

> 本节是当年全模态扩展的规划清单，现仅作历史参考。音视频/图片分支均已实现，
> 解析/切分/媒体处理实现也已从 `shared/utils` 下沉到 `engines/document/`。
> 当前权威结构见 `docs/knowledge-space/current/knowledge-architecture-navigation.md`。

### 4.1 Models — 已完成

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
| **`document_service.py`**（已拆分为 `document_pipeline` / `document_upload_service` / `document_task_service` / `document_query_service`） | **核心管道扩展**：新增音视频处理分支；`ALLOWED_FILE_TYPES` 扩展；空间类型校验逻辑重写 |
| **`search_service.py`** | **检索统一**：`search_by_mode()` 注册全模态模式；全模态缓存/rerank/LLM回答；`_enrich_results` 返回音视频字段 |
| `space_service.py` | 模型类型映射扩展；`_build_es_create_kwargs` 传递音视频维度；空间类型互斥校验需重写 |
| `embedding_service.py` | 新增音视频向量化缓存（格式对齐 `emb:{model}:{modal_type}:{hash}`） |
| `question_generation_service.py` | 已由 `_run_post_parse_tail` 统一调用，文本/音频/视频共用；图片分支不生成假设问题 |

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

### 4.6 Shared/Engines 层 — 已完成

| 文件 | 修改内容 |
|------|---------|
| `shared/document/validation/` | `EXTENSION_TO_MIME` 扩展音视频类型；`MAGIC_SIGNATURES` 新增音视频魔数 |
| `ai_models/` 模型类型 | `ModelConfigService` 支持音频嵌入模型类型 |
| `engines/document/media/` | 音频 ASR / 视频抽帧 / VLM 帧描述实现 |
| `engines/document/splitters/` | 音视频切片（`splitting.audio` / `splitting.video`） |
| `shared/mq/worker.py` | 文档处理任务区分音视频路径 |

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
| 允许上传的文件类型 | `pdf,doc,docx,txt,md,csv,html,json,jpg,jpeg,png,gif,webp,mp4,mov,avi,mkv,webm,mp3,wav,flac,aac,ogg,m4a` | `document_file_types.py`（`SUPPORTED_FILE_TYPES`，`document_routes.py` 派生白名单） |
| 单文件大小上限 | 文本/图片 100MB、音频 200MB、视频 500MB（KB 配置 `limits.max_file_size_mb` 可覆盖） | `document_upload_service.py`（`_MODALITY_MAX_SIZE_MB` / `_get_max_file_size`） |
| API 层硬上限 | 100MB | `document_routes.py`（`MAX_UPLOAD_SIZE`） |
| 图片文件类型 | `jpg,jpeg,png,gif,webp` | `document_file_types.py`（`IMAGE_FILE_TYPES`） |
| 批量上传最大数 | 200 个 | `document_routes.py`（`MAX_BATCH_FILE_COUNT`） |

> 注意：`SUPPORTED_FILE_TYPES` 不含 `xlsx/xls/pptx/ppt/epub`。DeepDoc 引擎虽实现了
> 这些格式的 parser，但上传白名单尚未放开；如需支持要先扩 `SUPPORTED_FILE_TYPES`
> 并确认解析策略配置（Excel/PPT/EPUB 仅支持 deepdoc）。
## 六、Wiki 自动生成（2026-09 落地）

文档解析成功终态后自动触发（`tasks/document_tasks.py` → `tasks/wiki_tasks.py` 入队，
REPROCESS 复用同一路径），由 `wiki_ingest_service.py` 四阶段 Map-Reduce 生成互相链接、
带 chunk 引文溯源的 Markdown 页面。**Wiki 页面不入 ES 检索**，是独立浏览层。

- 数据：`models/wiki.py` 四表（WikiPage / WikiPageRevision / WikiPageIssue / WikiIngestRecord）；
  软删唯一约束 `(kb_id, slug, deleted_flag)`；版本两级保留（软 50 只清 pipeline 来源 / 硬 200 全清）
- 并发：per-KB Redis 锁 + `TransientBusyError` 延后重入队；LLM 信号量只在
  `_call_llm_text/_call_llm_json` 单层获取（嵌套获取死锁教训见 `docs/knowledge-space/current/wiki-architecture.md`）
- API：`api/wiki_routes.py`（注意 `:path` 路由遮蔽——带后缀的路由要注册在贪婪路由之前）
- Agent 工具：`features/agent/tool/builtins/wiki_tools.py`（search / read / write / flag_issue）
- 前端：`WikiBrowserView.vue` 三页签 + `WikiGraphPanel.vue` 图谱 + `KbWikiSection.vue` 配置段

详见 `docs/knowledge-space/current/wiki-architecture.md`。

## 相关文档

- Wiki 架构：`docs/knowledge-space/current/wiki-architecture.md`
- 知识配置结构：`docs/knowledge-space/current/knowledge-config-structure-design.md`
- 事务边界约定：`docs/transaction-boundary-conventions.md`
- ES 索引结构：`docs/elasticsearch-index-structure.md`
