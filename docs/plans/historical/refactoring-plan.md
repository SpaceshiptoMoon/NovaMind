# 文档处理管道重构计划

> 历史说明：这是 2026-07-06 形成的一份早期重构计划，属于历史方案文档，不是当前仓库结构或实现状态的正式事实来源。
> 当前结构请优先查看 [`../../README.md`](../../README.md)、[`../project-structure-navigation.md`](../project-structure-navigation.md)、[`../knowledge-space/current/README.md`](../knowledge-space/current/README.md)。
> 如果只想快速理解这份历史计划的核心结论，请优先阅读 [`refactoring-plan-readable-summary.md`](./refactoring-plan-readable-summary.md)。

> 日期：2026-07-06
> 状态：历史计划，保留追溯用途

---

## 一、目标

这份历史计划希望把知识库文档处理链路从“以 `Document` 为中心的混合模型”重构为三个职责明确的层次：

1. `Document`
   只保存文件元数据和存储信息，不再承担处理状态追踪职责。
2. `DocumentTask`
   作为新增任务实体，记录每次处理的完整生命周期、状态、错误、配置快照和产出结果。
3. `KnowledgeBase.config`
   作为处理管道的结构化配置来源，统一承载解析、切分和问题生成参数。

---

## 二、当时识别出的主要问题

### 2.1 `Document` 职责混乱

历史计划认为，`Document` 同时承担了两类职责：

- 文件元数据：`filename`、`file_type`、`file_size`、`storage`
- 处理过程状态：`status`、`status_info`、`doc_metadata`、`processing_started_at`、`processed_at`

这会让“文件是什么”和“文件处理到哪里了”混在一起，增加后续维护成本。

### 2.2 多模态链路的切分入口不统一

当时的处理路径大致是：

- 文本：读取后直接切分
- 音频：对 ASR `segments` 直接切分
- 视频：对 VLM `descriptions` 直接切分

历史计划希望改成统一模式：先产出完整 Markdown 文本，再交给统一切分器。

### 2.3 配置语义不清晰

文档指出：

- 某些切分参数放在 `parsing.audio` 中，语义上不合理
- 前端配置分步与后端配置结构并不一致

因此，计划希望把解析配置和切分配置更清楚地分层。

### 2.4 任务追踪过度依赖 Redis

当时的任务追踪主要依赖 Redis 中的临时键值，问题包括：

- 只有短 TTL
- 缺少持久化任务记录
- 难以追溯“某份文档是用什么配置处理的”

### 2.5 存在一批死代码和历史遗留逻辑

计划文档列出过一批接近无外部引用的方法和字段，例如：

- `version_info`
- `increment_retry()`
- `update_status()`
- 若干仅围绕旧 `Document.status` 设计的仓储查询

---

## 三、历史方案中的目标结构

### 3.1 `Document` 只保留文件元数据

历史方案希望让 `Document` 更接近纯元数据模型，保留：

- 所属空间、知识库、上传者
- 文件名、类型、大小、哈希
- MinIO 存储路径
- `created_at` / `updated_at` / `deleted_at`

并将以下内容从 `Document` 中移出：

- `status`
- `status_info`
- `doc_metadata`
- `processing_started_at`
- `processed_at`
- `version_info` 及其相关派生逻辑

### 3.2 新增 `DocumentTask`

历史方案建议新增任务模型 `DocumentTask`，主要字段包括：

- `document_id`
- `kb_id`
- `space_id`
- `status`
- `job_id`
- `pipeline_config`
- `step_progress`
- `pipeline_result`
- `error_message`
- `retry_count`
- `queued_at`
- `started_at`
- `completed_at`

状态枚举意图是：

- `PENDING`
- `PROCESSING`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

### 3.3 配置结构调整

这份历史计划希望把知识库配置整理为：

- `parsing`
  - 文本解析参数
  - 图片解析参数
  - 视频解析参数
  - 音频解析参数
- `splitting`
  - 通用切分策略
  - 音频专属切分覆盖
  - 视频专属切分覆盖
- `question_generation`
  - 问题生成策略

其核心思想是：解析参数和切分参数不能继续混在一起。

---

## 四、关键设计原则

### 4.1 Markdown 作为统一桥梁

这是整份历史方案最核心的设计点之一。

无论原始文件是：

- `txt` / `md`
- `pdf` / `docx`
- `xlsx` / `csv`
- `pptx`
- `html` / `json`
- `jpg` / `png`
- `mp3` / `wav`
- `mp4` / `mkv`

历史方案都希望先把它们统一转为一份完整 Markdown 文本，再进入切分阶段。

这么做的理由包括：

- 容易审计实际进入切分器的内容
- 容易对同一份解析结果做重复切分
- 容易为新文件类型扩展“原始文件 -> Markdown”的解析器

### 4.2 任务应具备可追溯性

每次处理都应带着自己的：

- 配置快照
- 步骤进度
- 处理结果
- 失败原因

这样后续才能复盘某次处理到底发生了什么。

---

## 五、历史计划中的管道流程

计划中的目标流程大致如下：

1. 上传文件后创建 `Document`
2. 同时创建 `DocumentTask`，并把当时的 `KB.config` 快照写入任务
3. Worker 消费任务
4. Step 1：解析原始文件，产出完整 Markdown
5. Step 2：把 Markdown 上传到 MinIO
6. Step 3：统一从 Markdown 进行切分
7. Step 4：Embedding
8. Step 5：索引到 Elasticsearch
9. 最终把结果写回 `DocumentTask.pipeline_result`

其中，历史文档特别强调：

- Markdown 上传应发生在切分之前
- 解析与切分要解耦
- 多模态内容不应各自维护独立切分逻辑

---

## 六、当时计划影响的代码范围

### 6.1 后端新增

计划里提到的新增对象包括：

- `models/document_task.py`
- `schemas/document_task_schema.py`
- `repository/document_task_repository.py`

### 6.2 后端修改

计划里明确提到会调整的区域包括：

- `models/document.py`
- `schemas/document_schema.py`
- `schemas/knowledge_base_schema.py`
- `services/document_service.py`
- `services/media_processing.py`
- `services/knowledge_base_service.py`
- `repository/document_repository.py`
- `api/document_routes.py`
- `shared/mq/worker.py`
- `shared/mq/task_tracker.py`
- `shared/mq/__init__.py`
- `shared/utils/media_utils.py`

### 6.3 前端修改

计划里预计会同步调整：

- `api/types.ts`
- `api/knowledge/document.ts`
- `views/space/DocumentView.vue`
- `views/space/DocumentDetailView.vue`
- `views/space/KbConfigView.vue`
- `components/knowledge/document.ts`

---

## 七、历史计划中的实施步骤

原计划把工作拆成 10 个阶段：

1. 新建 `DocumentTask` 模型和相关 schema / repository
2. 精简 `Document` 模型
3. 调整知识库配置结构
4. 重构文档处理管道
5. 重构 worker 执行逻辑
6. 调整 repository 与 service
7. 调整 API routes
8. 调整前端类型、页面和状态展示
9. 清理 `task_tracker`
10. 做后端编译、前端类型检查和整链路验证

---

## 八、历史审查中列出的关键遗漏

历史文档后来又追加了一轮“完整性审查”，指出若干高风险遗漏，包括：

- `enqueue_process_document()` 需要真正创建 `DocumentTask`
- `execute_document_pipeline()` 需要围绕任务对象更新进度与结果
- 统计查询需要改成围绕任务表聚合
- `SplittingConfig` 需要能容纳音频/视频专属覆盖配置
- 配置更新校验需要覆盖 `splitting.audio` / `splitting.video`
- 旧的 `revive()` 路径需要替代方案
- 批量处理入口不能再依赖 `status=UPLOADED`
- 应考虑 DB 级并发防护
- orphan recovery 逻辑要从 `Document.status` 改到 `DocumentTask`

---

## 九、历史审查中列出的后续风险

文档还特别强调了几类风险：

- 很多逻辑直接依赖 `Document.status`
- 前端页面大量使用旧状态字段
- worker 中可能仍有直接依赖旧表的 raw SQL
- 统计查询依赖旧状态字段聚合
- 切分后如何保留时间戳、帧路径等 metadata 仍有设计未决项
- 是否引入 DB 级唯一约束和取消任务持久化语义仍未最终定案

---

## 十、不变范围

这份历史计划认为，下列内容不应该因为这次重构而发生业务含义变化：

- Elasticsearch 索引的总体定位
- MinIO 作为文件存储后端的角色
- 用户认证链路
- LLM / Embedding / ASR / VLM 等模型调用基础设施
- ARQ 任务队列机制本身
- 搜索、评估、Agent、Skill 等非文档处理主链路模块

---

## 十一、今天如何使用这份历史文档

- 如果你要理解当前仓库结构，不应以本文为准。
- 如果你要追溯“为什么会出现 `DocumentTask`、配置分层、统一 Markdown 桥梁”这类设计方向，本文仍有价值。
- 如果你只需要快速把握这份历史计划，请优先看 [`refactoring-plan-readable-summary.md`](./refactoring-plan-readable-summary.md)。
- 如果你要理解当前知识空间正式结构，请回到 [`../knowledge-space/current/README.md`](../knowledge-space/current/README.md)。
