# 修复计划：上传 500 / 分块分页 / ASR 路径 / VLM 降级 / 坐标泄漏

> 创建日期：2026-07-18
> 范围：本轮测试暴露的 5 类问题，按 P0→P2 分批修复。

## Context（为什么做这些改动）

本轮在「企业知识库」主线上做端到端测试，暴露出五类问题，彼此独立但都影响主流程或内容质量：

1. **上传接口 500（MissingGreenlet）** — `POST /spaces/{space_id}/knowledge-bases/{kb_id}/documents` 在批量上传时直接报 `sqlalchemy.exc.MissingGreenlet`，阻断上传。
2. **ASR 本地模型路径错位** — 所有音频文档转写失败、重试到上限后标记 FAILED。模型文件其实存在，只是代码找错了目录。
3. **DeepDoc 坐标标记泄漏进正文** — `@@1\t52.5\t426.8\t76.1\t88.6##` 这类 bbox 标记被写进 chunk 文本，污染知识库与 embedding。
4. **前端文档详情页** — 「返回文档管理」永远回第 1 页；分块为空仍显示「分块数 0 / Token 数 0」并渲染空分块区；分块列表固定 limit=10、不可选页大小、详情接口仍内嵌全量 chunk。
5. **视频 VLM 配额耗尽无降级** — 全帧 VLM 失败时整个任务失败，没有可切换模型或跳过降级路径。

目标：按优先级修掉以上五项，前后端契约同步，并补回归测试。

---

## 批次 P0-1：上传接口 MissingGreenlet

### 根因
- `document_service.upload_document` 返回 ORM `Document` 实例（`document_service.py:197/383`）；`upload_documents` 返回 `{"success": [Document, ...], "failed": [...]}`（`:433`）。
- 路由层在 `document_routes.py:197-199 / 204-205 / 253-258 / 271-274` 直接读 `doc.id / doc.filename / doc.file_size`。
- `expire_on_commit=False`（`database.py:112`）本身不会 expire；但 `upload_document` 的 `IntegrityError` 分支调用 `await self.session.rollback()`（`document_service.py:367`），SQLAlchemy 的 `rollback()` 默认 `expire_on_rollback=True`，会把 session 内**所有**实例 expire。
- 批量上传中，一旦后续某个文件撞 `uq_kb_file_hash` 触发 rollback，之前已成功提交的 `Document` 实例属性就被 expire；路由再读 `doc.id` → 同步懒加载 → 异步驱动无 greenlet 上下文 → `MissingGreenlet`。traceback 中 `_load_expired → load_scalar_attributes` 即此路径。

### 修复
让 service 层不把 ORM 实体泄漏到路由层：在 session 仍活跃、rollback 发生**之前**就把所需标量读出，封装成 DTO 返回。

- 新增轻量 DTO（复用现有 schema 风格，放 `schemas/document_schema.py`）：`UploadedDocumentResult(document_id: int, filename: str, file_size: int)`。
- `DocumentService.upload_document` 返回类型由 `Document` 改为 `UploadedDocumentResult`：在 `commit()` 成功后立即读取 `id/filename/file_size` 构造 DTO 再返回（soft-delete 复活分支 `:323` 与 create 分支 `:383` 都改）。
- `upload_documents` 返回 `{"success": List[UploadedDocumentResult], "failed": List[dict]}`（`:415` append DTO）。
- `document_routes.py` 路由层改用 DTO 字段：`doc.document_id / doc.filename / doc.file_size`（`:197-199 / 204-205 / 253-258 / 270-275`）。
- `audit_service.log_document_upload` 签名不变（`document_id: int`，`audit_service.py:223`），路由传 `doc.document_id`。
- 同步排查别处是否还依赖 `upload_document` 返回 ORM `Document`（grep `upload_document(` 调用点），一并改。

### 验证
- `pytest`，新增针对批量上传含一个重复哈希文件的回归测试：断言不抛 `MissingGreenlet`、成功项返回正确 `document_id/filename/file_size`、重复项进 `failed`。
- 手动：批量上传（含一个同哈希文件）确认 200。

---

## 批次 P0-2：ASR 本地模型路径错位

### 根因
- `audio_utils.py:96-102` `_get_local_whisper_model` 用 `Path(__file__).resolve().parent.parent.parent.parent / "models" / "faster-whisper" / "tiny"`。
- `__file__` 在 `backend/src/shared/knowledge/media_processing/audio/`，4 次 `.parent` 落到 `backend/src/shared/`，于是找 `backend/src/shared/models/faster-whisper/tiny`（与报错一致）。
- 注释写的是 `backend/models/faster-whisper/tiny/`，实际需要 5 次 `.parent`。磁盘上 `backend/models/faster-whisper/tiny/model.bin` 已存在。
- 路径完全硬编码，无 env/YAML 配置项；`process_audio_document`（`media_processing.py:274-301`）按 `asr_protocol` 严格路由，`"local"` 失败无降级。

### 修复
1. **主修**：把路径改成可配置，默认指向正确的 `backend/models/faster-whisper/tiny`。
   - 在 `backend/src/setting/yaml_config/config.py` 的 `ParsingConfig`（或 `AudioParsingConfig` 子节）新增 `local_whisper_model_dir: Optional[str] = None`；`loader.py` 读取对应 YAML/env。
   - 同步更新 `*.example` 模板（gitignored 的 yaml 不动，只动 example）。
   - `audio_utils.py` 改为：优先读配置，否则用修正后的默认路径（5 次 `.parent`，或更稳妥地基于 `backend/` 根推导，例如 `Path(__file__).resolve().parents[4]`）。保留 `local_files_only=True`。
2. **降级**：`process_audio_document` 的 `"local"` 分支，当本地模型缺失时，若用户还配置了 dashscope/openai ASR 凭据，记录 warning 后回退到云端，而不是直接 `RuntimeError` 失败整个任务。无任何云端凭据时再抛清晰业务异常（继承 `BaseAPIError` 并在 `startup.py` 注册），而非 `RuntimeError`。

### 验证
- 单测：构造默认路径，断言解析到 `backend/models/faster-whisper/tiny` 且 `model.bin` 存在。
- 手动：上传一个音频文件，`asr_protocol=local` 转写成功。

---

## 批次 P1-1：DeepDoc 坐标标记泄漏进正文

### 根因
- `deepdoc/parsers/pdf.py:49-50` `line_tag()` 产出 `@@<page>\t<x0>\t<x1>\t<top>\t<bottom>##`；`as_tagged_text()`（`:46-47`）把标签直接拼到文本前。
- `_parse_layout`（`:603-604`）与 `_parse_vision`（`:698-699`）用 `as_tagged_text()` 拼 `full_text`，所以 `full_text` 带全部 `@@...##`。
- `document_processing/pipeline/document_loader.py:432-454` 的 deepdoc rechunk 分支把带标签的 `parse_result.full_text` 直接喂给 `split_text`，原干净 `chunks` 被丢弃，重新切分出的 chunk 继承了标签 → 写进 ES / embedding。
- `DeepDocPdfBox.remove_tag`（`pdf.py:537-538`，正则 `@@[\t0-9.-]+?##`）已存在，但只在 `crop()` 内部用，未用于 rechunk 前。
- parser 内部 `_build_structured_chunks`（`:1305`）产出的 chunk 是干净的（标签单独存在 `position_tag`/`source_id`），仅 rechunk 路径泄漏。

### 修复
- 在 `document_loader.py` deepdoc rechunk 分支，喂给 `split_text` 之前对 `full_text` 调用 `remove_tag`（复用 `DeepDocPdfBox.remove_tag`，或把该正则抽到 deepdoc 公共工具供 loader 导入）。
- rechunk 后的 `DeepDocParseResult.full_text` 也用去标签版本（结构化 chunk 的位置信息已单独保存在 metadata，不依赖 full_text 里的标签）。
- 等价泄漏点（remote/upstream 各 parser 的 `_line_tag`）本次不逐个改，统一在 loader 入口 strip 即可兜底所有 deepdoc 系 parser。

### 验证
- `backend/tests/test_deepdoc_reading_order.py` 已存在，补充一条用例：带标签的 `full_text` 经过 loader rechunk 后，chunk 文本不含 `@@` / `##` 标记。
- 用 `test_data/` 下 PDF 跑解析，确认 ES 中 chunk content 无坐标标记。

---

## 批次 P1-2：前端文档详情页 + 分块分页（前后端契约同步）

### 后端
- 现状：`GET /{kb_id}/documents/{document_id}/chunks`（`document_routes.py:352-378`）返回 `list[ChunkResponse]`，无 total；`limit` 默认 10（`:363`）。`GET .../documents/{doc_id}` 详情接口（`:320-349`）又把 chunks（默认 10）内嵌进 `DocumentDetailResponse`。
- 改：
  - 新增 `ChunkListResponse`（`schemas/document_schema.py`）：`items: List[ChunkResponse]`、`total: int`、`page: int`、`size: int`。
  - chunks 接口 `response_model=ChunkListResponse`；service `get_document_chunks` 与 `ElasticsearchClient.get_document_chunks`（`elasticsearch_client.py:420`）增加 `track_total_hits=True` 或单独 `count` 调用返回 `total`。
  - 详情接口不再内嵌 chunks（移除 `:344` 的 `get_document_chunks` 调用与 `DocumentDetailResponse.chunks`，或保留字段但置空），分块统一由分页 chunks 接口加载。

### 前端
- **返回页码**：`DocumentView.vue`（列表）`goToDetail`（`:441-443`）push 时带 `?fromPage=${currentPage}`；`SpaceListView.vue` 的 `navBack`（`:364-386`）与 `DocumentDetailView.vue` 的 `backTarget`（`:184-189`）读取 `route.query.fromPage` 拼回列表路由；列表页 mount 时读取 `route.query.page` 恢复 `currentPage` 并 `fetchDocuments()`。
- **分块为空时隐藏**：`DocumentDetailView.vue:54-61` 给「分块数 / Token 数」加 `v-if="document.chunk_count > 0"` / `v-if="document.token_count > 0"`（或显示「无分块」）；整个 `chunks-section`（`:85-151`）加 `v-if="document.chunk_count > 0"`，无分块时不渲染。
- **分块分页**：用现有 `components/common/Pagination.vue`（支持 `pageSizes` + `update:pageSize`，列表页已用）替换 `DocumentDetailView.vue:142-150` 的裸 `el-pagination`；`chunkPageSize`（`:198`）改为 ref + sizes 选择器；`fetchChunks`（`:226-242`）改用新的 `ChunkListResponse`，`total` 取接口返回而非 `document.chunk_count`。
- `api/knowledge/document.ts:getDocumentChunks`（`:36-41`）返回类型改为 `ChunkListResponse`；`api/types.ts` 补 `ChunkListResponse`、按需调整 `DocumentDetail`（去掉 `chunks` 或保持可选）。

### 验证
- `npm run type-check` + `npm run lint`。
- 手动：列表第 3 页进详情 → 返回回到第 3 页；空分块文档不显示分块区与 0 计数；分块页可切换 page size 并正确翻页。

---

## 批次 P2-1：视频 VLM 配额耗尽降级

### 根因
- `media_processing.py:107-135` `process_video_document` 逐帧调用 `_describe_single_frame`；全帧失败时 `:133-135` `raise ValueError("...所有帧的VLM描述均失败...")`，异常上抛导致整个任务失败。
- `vlm_utils.py:28-60` `generate_vlm_text_with_fallback` 仅对 `enable_thinking` 错误重试，对 403/配额错误直接 re-raise，无模型轮换。
- 无 fallback VLM 模型配置、无「配额耗尽跳过 VLM」开关。

### 修复（轻量）
1. **错误分类 + 清晰失败**：把「全帧失败」由 `ValueError` 改为业务异常（继承 `BaseAPIError`，注册到 `startup.py`），错误信息区分「配额/鉴权类」与「其它」，便于用户看到可操作提示（如「VLM 配额已耗尽，请在模型管理切换模型」）。
2. **可选 fallback 模型**：在 `pipeline_config.parsing` 增加 `vlm_fallback_model`（可选）；`_describe_single_frame`（`:501-550`）在主模型抛 403/配额类错误时，按 `parsing_config` 取 fallback client 重试一次。
3. **跳过降级开关**：增加 `vlm_skip_on_quota_error`（默认 false）；为 true 时全帧配额失败不抛异常，改为写一条说明性 chunk（「视频画面描述因 VLM 配额不可用，已跳过」）并标记任务 partial，避免整任务失败丢掉音频/已有信息。

### 验证
- 单测：mock VLM client 抛 403，断言走 fallback 或按开关降级，任务不失败（或以清晰业务异常失败）。
- 手动：配额耗尽场景下视频任务不再硬失败。

---

## 执行顺序与提交策略

1. P0-1（上传 500）→ 提交。
2. P0-2（ASR 路径）→ 提交。
3. P1-1（坐标泄漏）→ 提交（含回归测试）。
4. P1-2（前端详情页 + 分块分页，前后端一起）→ 提交。
5. P2-1（VLM 降级）→ 提交。

> 多 agent 并行注意：P0-1 / P0-2 / P1-1 都改 `backend/src/features/knowledge_space` 或 `shared/knowledge`，互不重叠的文件可并行；P1-2 同时动前后端契约，建议独占一批。遵循根 `CLAUDE.md` 的 worktree 隔离与原子提交要求。

## 关键复用点

- DTO 风格：`schemas/document_schema.py` 现有 `DocumentUploadResponse / FailedFileItem / DocumentBatchUploadResponse`。
- 去标签正则：`deepdoc/parsers/pdf.py:537-538` `DeepDocPdfBox.remove_tag`。
- 前端分页组件：`components/common/Pagination.vue`（列表页 `DocumentView.vue:160-168` 已用）。
- ES 分页：`ElasticsearchClient.get_document_chunks`（`elasticsearch_client.py:420`），补 `track_total_hits`/`count`。
- 业务异常基类：`BaseAPIError` + 模块 `startup.py` 注册（CLAUDE.md 硬规则）。