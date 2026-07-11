# 文档处理管道重构计划

> 日期: 2026-07-06 | 状态: 待审阅

---

## 一、目标

将文档处理从"以 Document 为中心"重构为"Document + Task + KB 配置"三层清晰职责：

1. **Document** — 纯文件元数据，不再存储处理状态
2. **DocumentTask** — 新建，记录每次处理的完整生命周期
3. **KnowledgeBase.config** — 管道配置，结构化切分参数

---

## 二、现状问题

### 2.1 职责混乱

Document 表同时承担文件元数据 + 处理状态追踪两件事：
- `status` (UPLOADED/PROCESSING/COMPLETED/FAILED/DELETED) 混在一起
- `status_info` 存错误/重试，是纯任务数据
- `doc_metadata` 存 pipeline 结果（chunk_count 等），也是任务数据
- `processing_started_at` / `processed_at` 是任务时间线

### 2.2 管道切分不统一

- 文本：`processor.load_with_strategy()` 一步完成解析+切分，MD 是 chunks 拼回来的
- 音频：直接对 `segments` 切分（`_merge_segments_by_size`），不走 MD
- 视频：直接对 `descriptions` 切分（`_aggregate_descriptions`），不走 MD
- MD 文档只是"顺便上传"的副产品，不是切分的输入源

### 2.3 配置位置不对

- `audio.chunk_split_strategy` 和 `audio.chunk_size` 放在 `parsing.audio` 里，但这是切分参数
- 前端把音频切片放在 Step 4（切分策略），后端在 `config.parsing.audio` 里

### 2.4 任务追踪全在 Redis

- Redis `doc_task_tracker` Hash + `doc_cancel:{id}` String，7天/1小时TTL
- 没有持久任务记录，无法追溯"这个文档用什么配置处理的"

### 2.5 死代码

| 代码 | 位置 | 状态 |
|------|------|------|
| `version_info` / `get_version_info` / `get_version_number` | document.py:60,139-145 | 无外部引用 |
| `increment_retry()` | document.py:128-133 | 无外部调用 |
| `update_status()` | document_repository.py:226 | 无外部调用 |
| `get_by_space()` | document_repository.py:131 | 无外部调用 |
| `get_storage_size()` | document_repository.py:350 | 无外部调用 |
| `get_processing_documents()` | document_repository.py:444 | 无外部调用 |
| `get_uploaded_documents()` | document_repository.py:451 | 无外部调用 |
| `search_by_filename()` | document_repository.py:410 | 无外部调用 |

---

## 三、新架构

### 3.1 Document — 纯文件元数据

```python
class Document(BaseModel):
    __tablename__ = "documents"

    id            # PK
    space_id      # FK → knowledge_spaces
    kb_id         # FK → knowledge_bases
    uploader_id   # FK → users

    filename      # 原始文件名
    file_type     # pdf/docx/txt/mp3/mp4/...
    file_size     # 字节数
    file_hash     # SHA-256（去重）

    storage       # JSON: {minio_bucket, minio_object_name, parsed_text_object}

    created_at / updated_at / deleted_at

    # 关系
    tasks = relationship("DocumentTask", back_populates="document")
```

**删除的字段：**
- ~~status~~ → DocumentTask.status
- ~~status_info~~ → DocumentTask.error_message / step_progress
- ~~doc_metadata~~ → DocumentTask.pipeline_result
- ~~processing_started_at~~ → DocumentTask.started_at
- ~~processed_at~~ → DocumentTask.completed_at
- ~~version_info~~ → 删除（无外部引用，死代码）

**保留的字段：**
- `storage` — MinIO 路径 + `parsed_text_object`（文件的派生资源）
- `deleted_at` — 软删除（文件生命周期）
- `chunk_count` / `token_count` — 保留在 API 响应中（从 Task 的最新记录派生）
- `file_hash` — 文件去重

### 3.2 DocumentTask — 新建

```python
class DocumentTask(BaseModel):
    __tablename__ = "document_tasks"

    id              # PK
    document_id     # FK → documents.id
    kb_id           # 冗余，方便查询
    space_id        # 冗余，方便查询

    # 状态
    status          # PENDING → PROCESSING → COMPLETED / FAILED / CANCELLED
    job_id          # arq job ID

    # 配置快照（处理开始时 KB.config 的完整拷贝）
    pipeline_config  # JSON

    # 逐步骤进度
    step_progress    # JSON: {"parsed": "done", "split": "done", ...}

    # 处理结果
    pipeline_result  # JSON: {"chunk_count": 42, "segment_count": 120, ...}

    # 错误追踪
    error_message    # TEXT
    retry_count      # INTEGER

    # 时间
    queued_at        # 入队时间
    started_at       # 开始处理
    completed_at     # 完成/失败

    created_at / updated_at

    # 关系
    document = relationship("Document", back_populates="tasks")
```

**TaskStatus 枚举：**
```python
class TaskStatus(IntEnum):
    PENDING = 0      # 待处理
    PROCESSING = 1   # 处理中
    COMPLETED = 2    # 已完成
    FAILED = 3       # 失败
    CANCELLED = 4    # 已取消
```

**索引：**
```python
__table_args__ = (
    Index("idx_task_document", "document_id"),
    Index("idx_task_kb_status", "kb_id", "status"),
    Index("idx_task_status", "status"),
)
```

### 3.3 KnowledgeBase.config — 最终结构

```yaml
config:
  space_type: ["text", "image", "video", "audio"]
  description: ""

  # ===== 解析：原始文件 → MD =====
  parsing:
    # 文本解析
    extract_images: false
    extract_tables: true
    ocr_enabled: false
    preserve_structure: true
    encoding: "utf-8"

    # 图片解析
    vlm_description_enabled: false

    # 视频解析
    video:
      frame_interval: 5.0       # 抽帧间隔(秒)
      max_frames: 60            # 最大帧数

    # 音频解析（只保留ASR）
    audio:
      asr_model: "whisper-1"   # ASR 模型名

  # ===== 切分：MD → chunks（模态统一） =====
  splitting:
    strategy: "recursive"      # recursive | fixed_size | markdown | semantic
    chunk_size: 2000
    chunk_overlap: 100
    min_chunk_size: 500        # recursive 专属
    max_chunk_size: 2000       # markdown/semantic 专属
    similarity_threshold: 0.7  # semantic 专属
    batch_size: 20             # semantic 专属

    # 可选：音频专属切分，不配则走默认
    audio:
      strategy: "sentence"     # sentence | fixed
      chunk_size: 1000         # fixed 模式下的字符数

    # 可选：视频专属切分，不配则走默认
    video:
      strategy: "fixed"        # fixed（按字数聚合）
      chunk_size: 1500

  # ===== 生成：假设性问题 =====
  question_generation:
    enabled: false
    max_questions_per_chunk: 5
    prompt_template: null
    llm:
      model: null
      temperature: 0.3
      top_p: 0.9
      max_tokens: 2048
```

### 3.4 核心原则：MD 是解析与切分之间的唯一桥梁

不管原始文件是什么格式（txt / pdf / docx / xlsx / pptx / html / json / jpg / png / mp3 / wav / mp4 / mkv ...），**解析阶段的唯一产物是一份 Markdown 文档**，这份 MD 随后上传到 MinIO，再被切分器读取并切分为 chunks。

```
解析（模态相关）              切分（模态无关）
───────────────              ───────────────
  txt/pdf/docx/xlsx/...  ──→  full_text.md  ──→ splitter ──→ chunks
  mp3/wav/flac/...       ──→  transcript.md ──→ splitter ──→ chunks
  mp4/mov/avi/...        ──→  descriptions.md ──→ splitter ──→ chunks
  jpg/png/gif/...        ──→  description.md ──→ splitter ──→ chunks
```

**设计意图：**
- **可审计** — 任何时候都能从 MinIO 拉回这份 MD，查看"到底什么内容进入了切分器"
- **可复现** — 切分策略可调整后对同一份 MD 重新切分，无需重新解析原文件
- **可扩展** — 新增文件类型只需写一个 "原始文件→MD" 的解析器，无需改动切分、Embedding、ES 索引

### 3.5 管道执行流程

```
上传文件
  │
  ▼
Document (纯元数据记录)
  │
  ▼
enqueue → DocumentTask (status=PENDING, pipeline_config=KB.config快照)
  │
  ▼
Worker 取出
  │
  ├─ mark_processing()  → Task.started_at
  │
  ├─ Step 1: Parse — 原始文件 → MD全文
  │   │
  │   │  ┌────────────┬─────────────────────────────────────┐
  │   │  │ 文件类型    │ 解析方式                            │
  │   │  ├────────────┼─────────────────────────────────────┤
  │   │  │ txt/md     │ 直接读取 UTF-8 文本                  │
  │   │  │ pdf/docx   │ DocumentReader 提取全文              │
  │   │  │ xlsx/csv   │ 表格转 Markdown table                │
  │   │  │ pptx       │ 幻灯片内容逐页拼接                    │
  │   │  │ html/json  │ 提取文本内容                         │
  │   │  │ jpg/png    │ VLM 生成图片描述                     │
  │   │  │ mp3/wav    │ ASR 转写 → [HH:MM:SS] 带时间戳文本   │
  │   │  │ mp4/mkv    │ 抽帧 → VLM 逐帧描述 → 带时间戳聚合    │
  │   │  └────────────┴─────────────────────────────────────┘
  │   │
  │   └─→ 产出: full_text (纯文本/Markdown)
  │
  ├─ Step 2: 上传 MD → MinIO
  │   │ 路径: spaces/{space_id}/kbs/{kb_id}/parsed/{file_hash}.md
  │   │ 记录: Document.storage.parsed_text_object = 上述路径
  │   │ 落库: session.commit()  ← 立即持久化，不等后续步骤
  │   └─ Task.step_progress.parsed = "done"
  │
  ├─ Step 3: Split — MD全文 → chunks
  │   │ 输入: 从 MinIO 或内存读取 Step 2 的 MD 全文
  │   │ 策略: splitting.{modality} 有配 → 专属策略
  │   │        splitting.{modality} 没配 → splitting 默认策略
  │   └─ Task.step_progress.split = "done"
  │
  ├─ Step 4: Embedding → Task.step_progress.embedded = "done"
  │
  ├─ Step 5: ES Index → Task.step_progress.indexed = "done"
  │
  └─ mark_completed() → Task (status=COMPLETED, completed_at, pipeline_result)
```

---

## 四、涉及文件

### 4.1 后端 — 新增

| 文件 | 说明 |
|------|------|
| `models/document_task.py` | DocumentTask ORM 模型 + TaskStatus 枚举 |
| `schemas/document_task_schema.py` | DocumentTask Pydantic Schema |
| `repository/document_task_repository.py` | DocumentTask 数据访问层 |

### 4.2 后端 — 修改

| 文件 | 改动要点 |
|------|---------|
| `models/document.py` | 删除 status/status_info/doc_metadata/processing_started_at/processed_at/version_info；删除 mark_*/set_error/increment_retry/get_version_info/revive 方法；添加 tasks 关系 |
| `models/__init__.py` | 导出 DocumentTask, TaskStatus |
| `schemas/document_schema.py` | DocumentResponse 去掉 status/status_info/retry_count/error_message/processing_started_at/processed_at；status 改为从 Task 派生；保留 chunk_count/token_count |
| `schemas/knowledge_base_schema.py` | AudioParsingConfig 去掉 chunk_split_strategy/chunk_size；SplittingConfig 新增 audio/VideoSplitting 子配置；KnowledgeBaseConfigUpdate 新增 splitting.audio/splitting.video |
| `services/document_service.py` | upload_document 不再写 status；管道方法改为写 Task 而非 Document；execute_document_pipeline 拆分 parse→split→embed+index |
| `services/media_processing.py` | process_audio/process_video 去掉内部切分逻辑，只做转写/描述→拼MD→上传；切分统一走文本切分器 |
| `services/knowledge_base_service.py` | get_kb_document_stats 改用 Task 表计数；删除 document status 相关查询 |
| `repository/document_repository.py` | 删除 status 过滤参数（get_by_kb/count_by_kb）；删除死代码方法；stats 查询改为 join Task |
| `api/document_routes.py` | 响应格式调整；状态参数改为从 Task 查询；新增 GET /{doc_id}/tasks |
| `api/exceptions.py` | DocumentAlreadyProcessingError 改名为 TaskAlreadyProcessingError |
| `api/startup.py` | 异常注册更新 |
| `shared/mq/worker.py` | 全量改为操作 Task；_ensure_mark_failed raw SQL 改为 tasks 表；recover_orphan_documents 改为查 Task |
| `shared/mq/task_tracker.py` | bind/unbind/active_count 等函数改为 Task 持久化操作；保留 Redis 取消标记（精确取消需要低延迟） |
| `shared/mq/__init__.py` | enqueue_process_document 增加创建 Task 记录 |
| `shared/utils/media_utils.py` | upload_parsed_text_to_minio 路径改为 `parsed/{file_hash}.md` |

### 4.3 前端 — 修改

| 文件 | 改动要点 |
|------|---------|
| `api/types.ts` | Document 接口去掉 status/status_info/retry_count/error_message/processing_started_at/processed_at；新增 DocumentTask 接口；SplittingConfig 新增 audio/video；AudioParsingConfig 去掉 chunk_split_strategy/chunk_size |
| `api/document.ts` | 新增 getDocumentTask()；process 类接口返回 task_id |
| `views/space/DocumentView.vue` | status 过滤/展示改用 Task；isProcessing/isFailed/canProcess 读 Task 状态 |
| `views/space/DocumentDetailView.vue` | 详情页展示 Task 信息；chunk_count 改为从 pipeline_result 派生 |
| `views/space/KbConfigView.vue` | 音频切片从 Step 3 移到 Step 4 splitting.audio；视频切分配置新增 splitting.video |
| `utils/document.ts` | docStatusMap 改为 taskStatusMap；新增 taskStatusMap |

---

## 五、开发步骤

### Step 1: 新建 DocumentTask 模型
1. 创建 `models/document_task.py`
2. 创建 `schemas/document_task_schema.py`
3. 创建 `repository/document_task_repository.py`
4. 更新 `models/__init__.py` 导出

### Step 2: 改造 Document 模型
1. 删除 version_info 字段和方法
2. 删除 status/status_info/doc_metadata/processing_started_at/processed_at
3. 删除 mark_*/set_error/increment_retry/get_version_info/revive
4. 删除 DELETED 枚举值（deleted_at 足以判断软删除）
5. 添加 `tasks` 关系

### Step 3: 改造 KB Config 结构
1. AudioParsingConfig 去掉 chunk_split_strategy / chunk_size
2. SplittingConfig 新增 AudioOverride / VideoOverride 可选子配置
3. KnowledgeBaseConfigUpdate 同步更新
4. 前端 types.ts 同步

### Step 4: 重构管道逻辑
1. 拆分 `execute_document_pipeline` 文本分支：reader → MD上传 → splitter
2. 重写 `process_audio_document`：ASR → 拼MD → 上传 → 统一splitter
3. 重写 `process_video_document`：抽帧+VLM → 拼MD → 上传 → 统一splitter
4. 新增统一的 MD splitter（输入=MD全文，输出=chunks，支持 modality override）
5. MD 上传路径改为 `spaces/{s}/kbs/{kb}/parsed/{file_hash}.md`

### Step 5: 改造 Worker
1. 从操作 Document → 操作 DocumentTask
2. enqueue 时创建 Task（status=PENDING, pipeline_config=快照）
3. `mark_processing()` → Task
4. 管道各阶段更新 Task.step_progress
5. `mark_completed()` → Task (pipeline_result)
6. `_ensure_mark_failed` raw SQL → tasks 表
7. `recover_orphan_documents` → 查 Task 表

### Step 6: 改 Repository + Service
1. document_repository.py 删除死代码、移除 status 过滤参数
2. stats 查询改为 join Task 表（状态计数部分）
3. document_service.py 状态检查改为查 Task
4. knowledge_base_service.py get_kb_document_stats 改用 Task

### Step 7: 改 API Routes
1. 文档列表/详情的 status 字段改为从 Task 派生
2. 新增 `GET /{kb_id}/documents/{doc_id}/tasks`
3. process/reprocess/retry/cancel 返回 task_id

### Step 8: 改前端
1. api/types.ts — 新增 DocumentTask，Document 去状态字段
2. api/document.ts — 新增 getDocumentTask()
3. DocumentView — 状态展示/过滤读 Task
4. DocumentDetailView — 详情加 Task 信息
5. KbConfigView — splitting 加 audio/video 覆盖
6. utils/document.ts — docStatusMap → taskStatusMap

### Step 9: 清理 task_tracker
1. 持久化绑定/取消绑定改为 DB 操作
2. 保留 Redis 取消标记（需要低延迟取消检查）

### Step 10: 验证
1. 后端编译 `py_compile` 全部修改文件
2. 前端 `type-check` + `build-only`
3. 启动后端确认建表成功（新建 tasks 表）
4. 走通完整上传→解析→切分→索引流程

---

## 六、不变的部分

- ES 索引结构不改变
- MinIO 存储结构（除 MD 路径命名）
- 用户认证链路
- AI 模型调用（LLM/Embedding/ASR/VLM）
- arq 任务队列机制（max_tries、retry_base_delay 等）
- 搜索 / 评估 / Agent / Skill 等模块不涉及文档处理管道

---

## 七、完整性审查结果（3 agent 交叉验证）

### 7.1 关键遗漏（Critical）

| # | 遗漏 | 影响 | 补充到 |
|---|------|------|--------|
| 1 | `enqueue_process_document()` 不创建 Task 记录 | 核心需求缺失，无 Task 快照 | Step 5.2 |
| 2 | `execute_document_pipeline()` 无 Task 参数 | 无法写入 Task.step_progress / pipeline_result | Step 4 |
| 3 | `_build_stats_select()` 状态聚合需重写 JOIN | 统计查询复杂度大增 | Step 6.2 |
| 4 | `SplittingConfig` 歧视联合无法容纳 audio/video 子配置 | Schema 结构不兼容 | Step 3.2 |
| 5 | `_validate_config_updates()` 不校验 splitting.audio/video | 切分策略新字段无校验 | Step 3.3 |
| 6 | `revive()` 删除后 `upload_document()` 复活逻辑需要替代方案 | 同文件重传功能缺失 | Step 2.3 |
| 7 | `process_kb_documents()` 的 `status=UPLOADED` 查询无替代 | 批量处理入口失效 | Step 6.1 |
| 8 | 并发防护无 DB 级约束（ `UNIQUE (document_id) WHERE status IN (PENDING,PROCESSING)` ） | 竞态条件风险 | Step 1.3 |
| 9 | `recover_orphan_documents()` 查 `Document.status` 需改查 Task | 重启恢复失效 | Step 5.7 |
| 10 | `process_resume_task()` 共用 `TaskTracker` 基础设施，需决定同步迁移还是分叉 | 简历管道受影响 | Step 9 |

### 7.2 后端遗漏（High）

| # | 遗漏 | 补充到 |
|---|------|--------|
| 11 | ES chunk 的 `start_time`/`end_time`/`frame_paths` 元数据在统一 MD 切分后如何保留 | Step 4.4 |
| 12 | `_generate_questions_for_chunks_static()` 读 LIVE KB config 而非 `Task.pipeline_config` 快照 | Step 5.5 |
| 13 | `_handle_final_failure()` 已是死代码，应删除或正式启用 | Step 5.6 |
| 14 | `_ensure_mark_failed()` raw SQL 写 `documents` 表需改为 `document_tasks` | Step 5.6 |
| 15 | `delete_by_kb()` 软删时 Task 行不做级联处理 | Step 2.4 |
| 16 | `_list_by_parent()` 的 `status` 参数需改为 Task join | Step 6.1 |
| 17 | `DEFAULT_STORAGE` 常量死代码，可一并清理 | Step 2 |
| 18 | `get_deleted_by_hash()` 在 revive 删除后变为死代码 | Step 2.3 |
| 19 | `DocumentProcessor` 需新增 `read_full_text()`（reader-only）和 `split_text()`（splitter-only）两个新方法 | Step 4.1 |
| 20 | `ai_chat_service.py` 调用了 `DocumentProcessor.load_with_strategy()`，需适配 | Step 4.6 |

### 7.3 前端遗漏（High）

| # | 遗漏 | 补充到 |
|---|------|--------|
| 21 | Status 过滤值从 `uploaded`→`pending`，新增 `cancelled` | Step 8.3 |
| 22 | `isProcessing`/`isFailed`/`canProcess` 状态常量映射更新 | Step 8.3 |
| 23 | `KbConfigView.onSave()` 音频切分从 `parsing.audio` 移到 `splitting.audio` | Step 8.5 |
| 24 | `KbConfigView.onLoad()` 音频切分从 `parsing.audio` 读改为 `splitting.audio` | Step 8.5 |
| 25 | `buildSplittingConfig()` 需包含 audio/video 子配置 | Step 8.5 |
| 26 | `ProcessDocumentResponse` / `BatchProcessResponse` 需新增 `task_id` | Step 8.1 |
| 27 | `SplittingConfig` 类型需新增 audio/video override 字段 | Step 8.1 |
| 28 | `KBStats.uploaded_documents` 语义变化（是否重命名为 `pending_documents`） | Step 8.1 |
| 29 | `DocumentDetailView` 中 `doc_metadata.chunk_type/frame_count/segment_count` 改为读 `pipeline_result` | Step 8.4 |
| 30 | 前端目前无 Task 轮询/Store 机制用于实时进度展示 | Step 8.8 |
| 31 | `KbConfigView` 缺少视频切分 UI（form fields for videoChunkStrategy/videoChunkSize） | Step 8.5 |
| 32 | `canReprocess`/`isProcessing`/`isFailed` 计算属性需状态键值更新 | Step 8.4 |
| 33 | `DocumentDetailView.status` 展示源不明确（API 派生 vs 单独 Task 端点） | Step 8.4 |
| 34 | `getMaxFileSizeText` 已是死代码 | Step 8.7 |

### 7.4 设计决策待定

| # | 决策点 | 待定项 |
|---|--------|--------|
| A | `SplittingConfig` 结构调整 | 拆出 top-level 字段 `audio`/`video`，不再用歧视联合包裹 |
| B | ES metadata 保留方案 | 时间戳切分：按 `[HH:MM:SS]` 标记边界，不在两段之间截断 |
| C | 取消标记 | Redis（低延迟）+ Task.status=CANCELLED（持久），双重保障 |
| D | 并发防护 | 应用层 check + DB partial unique index |
| E | 软删级联 | Task 不级联软删（FK 仍有效），查询时排除 `document.deleted_at IS NOT NULL` |

---

## 八、风险点（更新）

## 七、风险点

| 风险 | 缓解措施 |
|------|---------|
| Document.status 在 30+ 处被查询过滤 | 逐处审计，分步替换为 Task join，不一次性改动 |
| 前端依赖 status 字段的展示逻辑 | 后端 API 兼容返回 status（从 Task 派生），前端渐进适配 |
| Raw SQL 直接写 documents 表 | worker.py:208 三层兜底改为写 tasks 表，独立测试 |
| Stats 查询依赖 Document.status 的 CASE WHEN | 改为 join Task 表，性能相当（Task 表更小） |
