# AI PPT 功能实现计划

## Context

在 NovaMind 平台中新增独立的「AI PPT」模块，用户输入主题后，LLM 生成结构化 HTML → BeautifulSoup 解析为幻灯片数据 → python-pptx 渲染 .pptx 文件，支持用户上传自定义 .pptx 模板。SSE 流式推送生成进度。

## 核心流程

```
用户输入主题 → LLM 流式生成 HTML → BeautifulSoup 解析 → python-pptx 渲染 → 上传 MinIO → 返回下载链接
```

## 新增依赖

- `python-pptx` — .pptx 生成与模板读取
- `beautifulsoup4` — HTML 解析

## 实现步骤

### Phase 1: 后端基础层（模型 / Schema / 异常 / 仓库）

创建 `backend/src/features/ppt/` 模块，遵循 DDD 分层：

**1. 异常** — `exceptions.py`
- `PptError(BaseAPIError)` 基类
- 子类：`PptSessionNotFoundError`、`PptGenerationFailedError`、`PptTemplateNotFoundError`、`HtmlParsingError`、`PptxRenderingError` 等

**2. 模型** — `models/`
- `ppt_session.py`：`PptSession` (session_id, user_id, topic, status IntEnum, template_id, ppt_file_url, slide_count, config JSON, started_at, completed_at)
- `ppt_template.py`：`PptTemplate` (user_id, name, file_url, preview_url, layout_names JSON, layout_count, is_public, is_builtin)

**3. Schema** — `schemas/ppt_schema.py`
- `PptGenerateRequest`：topic(2~500字)、slide_count(3~50)、template_id、language、llm_model、temperature、max_tokens
- `PptSessionResponse`、`PptListItem`、`PptListResponse`
- `PptTemplateResponse`、`PptTemplateListResponse`

**4. 仓库** — `repository/`
- `PptSessionRepository`：create、get_by_session_id、list_by_user、update_status、complete、delete
- `PptTemplateRepository`：create、get_by_id、list_templates、delete

### Phase 2: 后端服务层（核心逻辑）

**5. HTML 解析器** — `services/html_parser.py`

LLM 生成的 HTML 约定格式：
```html
<section class="slide title-slide"><h1>标题</h1><h2>副标题</h2></section>
<section class="slide content-slide"><h2>标题</h2><ul><li>要点1</li></ul></section>
<section class="slide two-column">...<div class="column-left">...</div><div class="column-right">...</div></section>
<section class="slide table-slide"><h2>标题</h2><table>...</table></section>
<section class="slide section-slide"><h1>章节标题</h1></section>
<section class="slide ending-slide"><h1>谢谢</h1></section>
```

解析流程：BeautifulSoup → 逐 `<section>` 提取 → 输出 `List[SlideData]`（layout/title/subtitle/bullets/table/columns）

容错：无 `<section>` 标签时整体作为单页内容兜底；code fence 自动剥离

**6. PPTX 渲染器** — `services/pptx_renderer.py`

- 自定义模板：`Presentation(template_path)`，按 layout name 匹配模板中的母版布局
- 默认主题：空白 Presentation + 内置样式（微软雅黑 / 32pt 标题 / 18pt 正文 / 深蓝色标题栏 / 16:9）
- 布局映射：title→layout[0], content→layout[1], 其他→blank layout + 手动创建文本框/表格
- 用 `asyncio.to_thread()` 包裹同步的 python-pptx 操作避免阻塞事件循环

**7. 模板管理** — `services/template_manager.py`

- 上传：接收 .pptx → `Presentation()` 提取 `slide_layouts` 名称列表 → 上传 MinIO → 写 DB
- 使用：从 MinIO 下载到临时文件 → 传给渲染器
- 启动时内置 2-3 套默认模板（`is_builtin=True`）

**8. 主服务** — `services/ppt_service.py`

SSE 流式生成流水线（参考 `DeepResearchService` 模式）：

```
1. 创建 DB 记录 (PENDING)
2. SSE progress: "正在生成内容..." (10%)
3. LLM 流式生成 HTML → SSE content 逐块推送 (10%-70%)
4. BeautifulSoup 解析 HTML → List[SlideData] (70%)
5. SSE progress: "正在渲染幻灯片..." (80%)
6. python-pptx 渲染 .pptx (80%-95%)
7. 上传 MinIO (95%)
8. 更新 DB (COMPLETED)
9. SSE done: {download_url, slide_count}
```

异常处理：Rerank 降级模式 → 任何异常 catch → 标记 FAILED → SSE error 事件

LLM Prompt 设计要点：
- 严格约束输出只含 HTML，无解释文字
- 定义 7 种 slide 类型的 HTML 结构
- 模板可用时注入布局名称列表
- 使用 `---主题开始---/---主题结束---` 分隔符防注入

### Phase 3: 后端 API 层与集成

**9. API 路由** — `api/routes.py`（prefix: `/api/v1/ppt`）

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /generate/stream | SSE 流式生成（主入口）|
| GET | /sessions | 列表（分页、状态过滤）|
| GET | /sessions/{id} | 详情 |
| GET | /sessions/{id}/download | 下载（重定向到 MinIO presigned URL）|
| DELETE | /sessions/{id} | 删除 |
| POST | /templates | 上传模板（multipart/form-data）|
| GET | /templates | 列表 |
| DELETE | /templates/{id} | 删除 |

**10. DI 与异常处理** — `api/dependencies.py`、`api/exception_handlers.py`
- `get_ppt_service` 通过 `Depends(get_db)` + `ModelConfigService` 注入
- `setup_ppt_exception_handlers(app)` 注册异常映射

**11. 集成注册**（修改现有文件）
- `router_manager.py`：导入 router，添加 prefix `/api/v1/ppt`，tag `AI PPT`
- `exceptions.py`：调用 `setup_ppt_exception_handlers(app)`
- `startup_manager.py`：`_import_models()` 中导入 `PptSession`、`PptTemplate`

### Phase 4: 前端

**12. 类型** — `api/types.ts` 添加接口
- `PptGenerateRequest`、`PptSession`、`PptListResponse`、`PptTemplate`、`PptTemplateListResponse`

**13. API 模块** — `api/ppt.ts`
- `streamGenerate`：使用 `createSSEStream`，回调 onProgress/onContent/onDone/onError
- `listSessions`、`downloadPpt`、`deleteSession`
- `uploadTemplate`（FormData + 上传进度）、`listTemplates`、`deleteTemplate`

**14. Store** — `stores/ppt.ts`
- 状态：isGenerating、progressPercent、generatedHtml、currentSession、sessions、templates
- 方法：generateStream、fetchSessions、fetchTemplates、cancelGeneration

**15. 页面**
- `views/ppt/PptView.vue`：主题输入 + 幻灯片数量 + 模板选择器 + 生成按钮 + 进度条 + HTML 实时预览 + 下载按钮
- `views/ppt/PptHistoryView.vue`：历史列表（主题/页数/状态/时间/操作）+ 分页

**16. 路由 & 布局**
- `router/index.ts`：添加 `/home/workspace/ppt` 和 `/home/workspace/ppt/history`
- `WorkspaceLayout.vue`：channels 数组新增 `{ key: 'ppt', label: 'AI PPT' }`，sidebar 新增 PPT 操作区，switchChannel 映射补充 ppt 路径

## 关键参考文件

| 用途 | 文件路径 |
|------|---------|
| SSE 流式模式 | `backend/src/features/deep_research/services/deep_research_service.py` |
| 路由注册 | `backend/src/core/middleware/router_manager.py` |
| 启动集成 | `backend/src/core/middleware/startup_manager.py` |
| 异常注册 | `backend/src/core/middleware/exceptions.py` |
| 前端 SSE | `frontend/src/api/index.ts` (createSSEStream) |
| 前端布局 | `frontend/src/layouts/WorkspaceLayout.vue` |
| 前端路由 | `frontend/src/router/index.ts` |
| MinIO 客户端 | `backend/src/shared/storage/minio_client.py` |
| 心跳工具 | `backend/src/shared/utils/heartbeat.py` |

## 验证方式

1. 启动后端，确认 `ppt_sessions` 和 `ppt_templates` 表自动创建
2. 调用 `POST /api/v1/ppt/templates` 上传一个 .pptx 模板，确认 layout_names 正确提取
3. 调用 `POST /api/v1/ppt/generate/stream`，观察 SSE 事件序列：progress → content → progress → done
4. 下载生成的 .pptx，确认内容与输入主题一致，幻灯片数量正确
5. 使用自定义模板生成，确认使用了模板的母版布局
6. 前端：输入主题 → 生成 → 实时预览 → 下载 → 历史列表查看
