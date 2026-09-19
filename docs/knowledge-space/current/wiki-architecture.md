# Wiki 生成与浏览架构

> 最后更新：2026-09-18。Wiki 机制移植自腾讯 WeKnora，归属 `features/knowledge_space/` 内部（不建独立 feature）。
> 端到端实测通过：16 页 / 72 互链 / 0 孤儿，编辑-版本-回滚-Agent 工具全链路可用。

## 定位

文档解析完成后，LLM 管道把知识库文档自动整理成**互相链接、带引用溯源、可编辑可回滚**的 Markdown 页面（实体页 / 概念页 / 摘要页）。Wiki 是知识库的**浏览层升级**：

- **不入 ES 检索**：wiki 页面只存在于 MySQL，不参与 RAG 检索链路，是独立的阅读视图。
- **引用强制接地**：写作前先做 chunk 级引文标注，无 citation 的候选不写页（反幻觉）。
- **slug 连续性**：文档重解析时提示词强制复用旧 slug，页面身份稳定。

## 数据模型（`models/wiki.py`）

| 表 | 说明 |
|---|---|
| `wiki_pages`（WikiPage） | 页面主表：slug/title/page_type(summary,entity,concept,synthesis,comparison)/content/summary/aliases/source_refs/chunk_refs/in_links/out_links/version/last_edit_source |
| `wiki_page_revisions`（WikiPageRevision） | 版本快照，唯一约束 `(page_id, version)`，两级保留（软 50 只清 pipeline 来源 / 硬 200 全清） |
| `wiki_page_issues`（WikiPageIssue） | 问题登记（实体混淆/事实矛盾/过期等），人工与 Agent 共用闭环 |
| `wiki_ingest_records`（WikiIngestRecord） | 生成任务履历：status + step_progress JSON（崩溃可见） |

**软删唯一约束**：`deleted_flag BIGINT`（0=存活，删除写时间戳）配唯一索引 `(kb_id, slug, deleted_flag)`。MySQL 无 partial index，不要改回 Postgres 方案。

**配置段**：`KnowledgeBaseConfig.wiki: WikiGenerationConfig`（enabled / llm / granularity(focused,standard,exhaustive) / max_pages_per_ingest / content_instructions / extraction_instructions），见 `schemas/knowledge_base_schema.py`。

## 生成管道（`services/wiki_ingest_service.py`）

四阶段 Map-Reduce：

```text
Pass 0 候选抽取   LLM 抽实体/概念 slug 骨架；提示词喂入 KB 已有 slug（slug 连续性）
Pass 1 引文标注   chunk 分批 → LLM 标注 {slug: [chunk_id]}；无引用的候选直接丢弃
Reduce 写页       并发生成 SUMMARY + Markdown 正文（[[slug|title]] 互链、只用已标注 chunk 原文）；
                  已有页面走合并更新（内容变化才 bump version，旧版先快照）
Finalize 收尾     in/out_links 双向对齐、死链剔除、revision 两级裁剪（纯代码无 LLM）
```

并发与锁：

- **per-KB Redis 锁** `wiki:kb_lock:{kb_id}`（TTL 30min），拿不到 raise `TransientBusyError` 延后重入队。
- **LLM 并发控制只在 `_call_llm_text` / `_call_llm_json` 单层获取** `asyncio.Semaphore(4)`。
  ⚠️ 严禁在外层再嵌套获取同一 Semaphore——嵌套获取会死锁（外层持锁者等内层许可，许可被「持一半」的协程占死，gather 永久挂起且无日志）。
- **DB 写串行**：AsyncSession 不安全于 gather 并发写，页面落库在 gather 之外逐个执行。

触发与重入：

- 文档解析成功终态后 `_trigger_wiki_ingest_if_enabled` 自动入队（`tasks/document_tasks.py`，try/except 吞异常不影响文档任务）；REPROCESS 重解析天然复用。
- 存量文档补算走 `POST .../wiki/rebuild`（逐文档入队）。
- arq 任务 `process_wiki_ingest_task`（`tasks/wiki_tasks.py`，嵌入式 worker）。

## API（`api/wiki_routes.py`）

前缀 `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/wiki`：

- 读：`GET /pages`、`GET /pages/{slug:path}`、`GET /pages/{slug:path}/sources`、`GET /index`、`GET /search`、`GET /stats`、`GET /ingest/status`、`GET /graph`、`GET /lint`、`GET /issues`
- 写：`POST /pages`、`PUT /pages/{slug:path}`（version 乐观锁，冲突 409）、`DELETE /pages/{slug:path}`（软删）
- 版本：`GET /revisions/{slug:path}`、`GET /revisions/{slug:path}/{version:int}`、`POST /revert`
- 运维：`POST /rebuild`、`PUT /issues/{id}/status`

⚠️ **路由注册顺序**：`/pages/{slug:path}/sources` 必须注册在 `/pages/{slug:path}` **之前**——`:path` 转换器贪婪吞掉后缀，顺序反了 sources 永远 404。`/revisions/{slug:path}/{version}` 还需 `:int` 转换器。

**版本语义**：仅用户可见字段（title/content/summary/page_type/status）变更才 bump version；链接维护等簿记写不动 version。回滚 = 用旧版内容创建新版本（`edit_source=revert`），可再回。

## Agent 工具（`features/agent/tool/builtins/wiki_tools.py`）

类名 `WikiTool`（非 Toolset），4 个工具：

- `wiki_search(queries, kb_ids?)` / `wiki_read_page(slugs)` — 读
- `wiki_write_page(...)` — 仅 synthesis/comparison 两类（跨文档综合页，Agent 专属），EDITOR+ 权限，`[[slug|...]]` 出链对已有 slug 校验
- `wiki_flag_issue(slug, issue_type, description)` — 报问题进 `wiki_page_issues`，与人工处理共用闭环

## 前端

- **`views/space/WikiBrowserView.vue`**：三页签（浏览/图谱/问题）。浏览 = 左列表 + 右 MD 正文 + 来源折叠面板；`[[slug|title]]` 渲染前正则替换为 `<a data-slug>` 再 `renderMarkdown`；编辑抽屉（乐观锁 409 提示）+ 历史抽屉（行级 diff + 回滚，diff 在 `utils/wikiDiff.ts`）；生成中顶部横幅轮询 `/ingest/status`。
- **`components/knowledge/WikiGraphPanel.vue`**：ECharts 力导向图谱（overview / ego 邻域），按 page_type 着色 + 图例过滤、拖拽/缩放、悬停提示、点击跳页面；颜色读 Element Plus CSS 变量适配暗色主题；echarts 按需引入（Graph/Tooltip/Legend），仅随 Wiki 懒加载 chunk 下载。
- **`components/knowledge/KbWikiSection.vue`**：KB 配置「Wiki 生成」步骤（`kbConfig.ts` 的 `applyWikiConfig` / `buildWikiConfigFromForm` 双向转换）。

## slug 规范化

`normalize_slug`：小写、空白与非法符号转 `-`、**保留 `/`（层级 slug）与 CJK 原字符**（未引 pypinyin，URL 美化后续再说）。

## 相关文件

- 模型：`backend/src/features/knowledge_space/models/wiki.py`
- 管道：`backend/src/features/knowledge_space/services/wiki_ingest_service.py`
- 仓储：`backend/src/features/knowledge_space/repository/wiki_repository.py`、`wiki_issue_repository.py`
- 路由：`backend/src/features/knowledge_space/api/wiki_routes.py`
- 任务：`backend/src/features/knowledge_space/tasks/wiki_tasks.py`
- Agent：`backend/src/features/agent/tool/builtins/wiki_tools.py`
- 提示词：`backend/src/features/knowledge_space/prompts/templates.py`（`wiki_` 前缀四组）
- 前端：`frontend/src/views/space/WikiBrowserView.vue`、`frontend/src/api/knowledge/wiki.ts`
