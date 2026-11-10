# Agent Handover：知识库文档详情页 video chunk 帧图缩略条（2026-11-11）

> 交接对象：接手 NovaMind 知识库前端/后端迭代的下一位 Agent 或维护者。
> 本文是时间快照（见上级 README 约定），路径与状态请以你接手时的仓库现状复核。

## 一句话结论

任务已**完成、验证、提交**：文档详情页 video 分块展开后现在会显示帧图缩略条（点击可放大翻帧）。
功能提交 `afd9e565`、文档提交（本交接书 + 权威文档补节）均在本地 `main`，**未推送**。
无进行中的半成品，无未落盘的改动。

## 任务背景

用户报告：空间「模块化E2E-1029」（space_id=38）→ 知识库「多媒体矩阵kb」（kb_id=108）→ 文档管理，
页面不显示 chunk 对应的图片。

诊断结论（实测，非猜测）：该 KB 17 个文档全是音视频（doc 975–995）。chunk 配图有三条独立链路，
本次缺的是第三条：

| 链路 | 载体 | 状态（修复前） |
|------|------|----------------|
| 文档 figure（pdf/docx/xlsx 等） | content 里 `](figure_xxx.png)` → 端点 `presign_figure_links` 换签 | 一直正常 |
| image 类型 chunk | 顶层 `media_url`（预签名原图） | 一直正常（该 KB 没有此类文档） |
| **video 类型 chunk** | `metadata.frame_urls`（预签名帧图列表） | **两处断点：chunks 端点不签发 + 前端零消费** |

关键陷阱：video chunk 的 `media_url` 指向**原视频文件**（实测 Content-Type `video/mp4`），
`<img>` 渲染不了它——不能拿 media_url 当图。帧图真正存放在 `metadata.frame_paths`
（MinIO 对象名，未签名，浏览器直连必 403）。audio chunk 无图是预期行为（转写文本 only）。

## 交付内容（commit `afd9e565`，7 文件）

方案要点：**没有发明新字段**。检索端点已有 `metadata.frame_urls` 预签名约定
（`search_service` + SearchView），按「不造第二套实现」原则两端点统一到同一约定。

- `backend/src/features/knowledge_space/services/document_query_service.py`
  新增共享静态方法 `presign_frame_urls(metadatas, minio_client, max_urls=MAX_FRAME_URLS)`：
  批量把 `frame_paths` 换签写回 `metadata.frame_urls`（响应层派生字段，**不回写 ES**）；
  常量 `MAX_FRAME_URLS=9` 是两处展示口径的单一来源；单帧签名失败跳过该帧、全部失败不写键；
  非 dict / `frame_paths` 非列表的项跳过。
- `backend/src/features/knowledge_space/services/search_service.py`
  `_presign_frame_urls` 改为委托上面的共享实现（行为不变；保留模块级 `get_minio_client()`
  调用以兼容既有测试的 monkeypatch）；`_MAX_FRAME_URLS` 取共享常量。
- `backend/src/features/knowledge_space/api/document_routes.py`
  chunks 端点在构建响应前批量预签名（传 `document_query_service.minio_client`，构造必传非 None）。
- `backend/src/features/knowledge_space/schemas/document_schema.py`
  无新字段；`media_url` 描述文案修正为「预签名 URL（原件）」。
- `backend/tests/features/knowledge_space/test_document_frame_presign.py`
  新增 8 用例（含「字符串 frame_paths 被当序列切片会按字符签名」的防回归断言）。
- `backend/tests/fixtures/openapi_baseline.json` 基线刷新（diff 定性后仅 1 行描述文案变更）。
- `frontend/src/views/space/DocumentDetailView.vue`
  chunk 卡片新增 `frameThumbsOf` 分支：el-image 帧条（120×68 cover，规格同 SearchView；
  `preview-src-list` 点击放大可翻帧；`preview-teleported` 防层叠上下文压住查看器），
  帧条置于 VLM 帧描述正文之上。`types.ts` 零改动（经 `metadata` Record 读取）。

## 验证记录（全部通过）

1. 单测：`test_document_frame_presign.py`（8 新）+ `test_search_frame_presign.py`（5 旧，证明委托重构保行为）13/13 绿。
2. 门禁：import 无环（`test_import_acyclic_gate.py`）、openapi 快照（刷新后）均绿；ruff 全过；前端 type-check / eslint / prettier 全绿。
3. API 真机 18 断言：帧序一致、URL 实取 JPEG 魔数、sintel 89/89 chunk 全覆盖、audio 不误伤、`media_url` 契约未破。
4. 页面真机 24 断言（Playwright + 本机 Edge）：折叠态不渲染、帧图全加载、computed 尺寸实测 120×68
   （scoped 样式确实落到 el-image 根节点）、点击第 N 张预览层开第 N 帧、可翻帧、预览层 teleport 到 body、
   audio 无帧条、暗色主题同渲染；零 console 错误、零 4xx/5xx。
5. 视觉复核（eyes 子代理，双主题截图）：PASS；仅存量瑕疵（见下）。

复验命令（在你机器上，约 2 分钟）：

```bash
# 单测 + 门禁
cd backend && .venv/Scripts/python.exe -m pytest tests/features/knowledge_space/test_document_frame_presign.py tests/features/knowledge_space/test_search_frame_presign.py tests/architecture/test_import_acyclic_gate.py tests/architecture/test_openapi_contract_snapshot.py -q
# API 真机（需后端 8100 + MinIO 9005 + ES 9200 在跑；脚本读 .env 的 ADMIN_PASSWORD）
cd .. && backend/.venv/Scripts/python.exe .tmp/probe_frame_urls_e2e.py
# 页面真机（另需前端 5173 在跑；截图输出 .tmp/chunk_frames_shots/）
node .tmp/verify_chunk_frames.mjs
```

注意：`.tmp/` 被 gitignore，探针/截图是**本机资产不入库**；详情页路由形态是
`/home/spaces/38/documents/980?kbId=108`（kbId 是 query，缺省时前端走 `GET .../documents/{id}/kb-id` 反查）。

## 当前运行环境（写就于交接时刻）

全栈在跑且均为**独立进程**（父进程已退出，不随终端/会话回收）：后端 8100（PID 29596 启动器 + 14916 解释器）、
前端 Vite 5173、MinIO 9005（PID 3188）、ES 9200（PID 26804）；MySQL/Redis 是 Windows 服务。
后端已加载新代码（重启于验证前）。`/health/detailed` 五组件 healthy。

改后端代码后要重启才生效（非 `--reload`）。**重启前先查 arq 队列**：
`/d/S-redis/redis-cli LLEN arq:queue` 与 `KEYS 'arq:in-progress*'`，非空说明有解析任务在跑，
此时杀 worker 会留僵尸 job（历史教训）。停进程用 PowerShell `Stop-Process -Id <pids> -Force`
（Git Bash 的 `taskkill /F` 会被路径转换吞掉），启动命令见 `local-infra` 相关经验（PowerShell `Start-Process` 分离进程）。

## 遗留与待决（按优先级）

1. **推送决定（用户）**：提交本交接书后，本地 `main` 相对本地记录的 `origin/main` 领先 38 个提交——
   本任务占 2 个（功能提交 `afd9e565` + 本交接书所在的 docs 提交），其余 36 个是此前多批会话的积累
   （详见 `git log origin/main..HEAD`）。是否推送、何时推送由用户定；推送前 hook 会扫描密钥。
2. **存量 bug（已实证未修，超出本任务范围，待用户拍板）**：「已向量化」徽章恒不亮。
   根因：ES 9.2+ 新建索引默认 `index.mapping.exclude_source_vectors=true`，`_source` 不再含
   `embedding` 向量，而 `document_routes.py` 的 `_build_chunk_response` 用
   `c.get("embedding") is not None` 判定 → 恒 False（实测向量实际存在，`exists` 查询 2/2 命中，
   `_source.exclude_vectors=false` 可取回 1024 维）。波及面已核：后端仅此一处、前端仅
   DocumentDetailView 徽章一处，纯展示 P3，不影响检索。修法方向（版本无关、勿为布尔拉回向量）：
   查询加命名子句 `{"exists":{"field":"embedding","_name":"has_vec"}}`，按 `matched_queries` 判定；
   需补正反用例。探针 `.tmp/probe_has_embedding_rootcause.py`。
3. **可选增强（未做）**：帧图点击放大处可加「跳转文档级播放器对应 `metadata.start_time`」
   （检索页 SearchView 的 `playClip` 已有 `/stream` Range + `#t=` 媒体片段先例可参照）。
4. **存量瑕疵（非本次引入，未处理）**：暗色主题下 chunk 的「关键词/假设问题」标签行对比度偏弱；
   页面右下角全局悬浮按钮轻微遮挡内容。属全局样式层，建议与工作台 UI 批次一起看。
5. **多 Agent 提醒**：若你与其他 Agent 并行开发，按仓库 AGENTS.md 用独立 worktree + 分支，
   主工作目录只做集成合并。本任务是单 Agent 直接在主工作目录完成的（用户在场指派）。

## 环境速查（本机已知陷阱）

- 8GB 内存：机器紧张期不跑全量 pytest（历史 OOM 教训），跑定向测试；本任务全程只跑定向。
- Python 一律 `backend/.venv/Scripts/python.exe`（仓库根没有 .venv；`python` 可能是 Windows Store 存根）。
- Vite 只监听 IPv6 `[::1]:5173`，IPv4 curl 探活会误判；浏览器访问正常。
- 登录 `POST /api/v1/user/users/login`（注意带 `/user` 前缀），admin + 仓库根 `.env` 的 `ADMIN_PASSWORD`。
- 浏览器验证用 Playwright + 本机 Edge（`channel: 'msedge'`，库在 npx 缓存）；
  `agent-browser` 在本机会卡死，勿用。主题切换 localStorage 键 `novamind-theme` 是裸字符串非 JSON。
- 本会话期间 ZCode 的模型服务曾出现 provider 401（认证过期类），与仓库代码无关，无需排查代码。

## 相关文档

- 配图三链路的正式说明（本次同步补入）：`docs/knowledge-space/current/document-processing-flow.md`
  的「分块配图的读取端三链路」一节；其上一节「figure 盐化占位符链」是文档 figure 的权威出处。
- 代码先例：检索页帧图缩略条——`frontend/src/views/space/SearchView.vue` 的 `frameThumbsOf` 与 `.result-frames` 样式。
- Agent 持久记忆（ZCode memory，非仓库文件）：`kb-chunk-frame-image-gap-2026-11`（本任务全貌）、
  `es9-source-vectors-excluded-has-embedding`（遗留 2 的实证细节）、`local-infra-services-no-docker`（服务启停）。
