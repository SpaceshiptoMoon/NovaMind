# NovaMind「企业内部知识库 + 智能答疑」改进路线图

> **定位目标**：把 NovaMind 从「功能齐全的 AI 平台」收敛为「**企业可信、可追溯、可进化的智能知识库**」。
> **北极星指标**：用户每次提问都能得到「**带引用、可追溯原文、答错会拒答**」的回答。
> **文档性质**：开发路线图，每项标注涉及文件 / 接口 / 技术方案 / 验收标准，可直接拆任务。
> **事实来源**：所有「现状」结论均来自 2026-06-15 对源码的逐行核实，附文件:行号。

---

## 一、定位校准：为什么是这个场景

NovaMind 当前能力铺得很广（知识库 / 问答 / 深度研究 / 评估 / Agent / 技能市场 / 简历 / 终端），但**没有一条主线**。建议以「企业内部知识库 + 智能答疑」为主线收敛产品：

- **目标用户**：中大型企业、政企、垂直专业领域（法律 / 医疗 / 金融 / 咨询 / 制造）。
- **核心价值主张**：私有化部署 + 团队知识沉淀 + **可信可溯源问答** + RAG 效果可度量。
- **差异化对标**：`MaxKB / FastGPT` 的产品形态 + `RAGFlow` 的检索深度 + `Ragas` 的测评（已有，独有护城河）+ 私有化。

**收敛原则**：新功能必须服务于「让问答更可信 / 让知识更易沉淀」，否则暂缓。Agent、技能市场、ClawMate 终端作为「进阶能力」保留，但不作为主线叙事。

---

## 二、现状诊断

### 2.1 核心结论

> **检索引擎已是企业级，但问答层是「无根对话」。**
> `qa` 模块的对话服务**完全没有调用知识库检索**，是纯 LLM 上下文拼接 + 裸生成。这导致整个产品最核心的「知识库问答」名不副实——首页宣传「每条回复可溯源至原文」，实际从未实现。

### 2.2 能力矩阵（绿=达标 / 黄=半成品 / 红=缺失）

| 维度 | 能力 | 现状 | 关键证据 |
|------|------|------|---------|
| 检索质量 | 9 种检索模式 | 🟢 | `search_service.py:590` / `elasticsearch_client.py:826` |
| 检索质量 | Rerank 重排序 | 🟡 默认关、QA 不调 | `search_service.py:868`；qa 模块未引用 |
| 检索质量 | RRF 融合（多层） | 🟢 | `elasticsearch_client.py:562` |
| 检索质量 | 查询改写 HyDE / 子查询 | 🟢 QA 已接 QueryRewriter (4 策略) | `query_rewriter.py`；`ai_chat_service._prepare_chat` |
| 检索质量 | 检索降级链 | 🟢 | `search_schema.py:411` |
| **回答质量** | **QA 接入知识库检索** | 🟢 **完整 RAG 管道已落地** | 会话级 `auto_rag` + QueryRewriter + GradeRetry + Trace；`ai_chat_service.py` 详见 REFACTOR-qa-rag-pipeline.md |
| **回答质量** | **引用溯源 / Citation** | 🔴 **缺失** | `qa/schemas/qa.py` 无 sources 字段 |
| **回答质量** | **防幻觉 / 拒答** | 🟡 **分级拒答开关就位** | `session_config` 的 `refusal_enabled` + `score_threshold` 控制；前端差异化展示待做 |
| 回答质量 | FAQ / 高频问题加速 | 🔴 缺失 | 全仓无 faq |
| 功能完整 | 多轮上下文压缩（4 策略） | 🟢 | `qa_service.py:499` |
| **功能完整** | **用户反馈（👍👎/纠错）** | 🔴 **缺失** | qa 模块 feedback 0 命中 |
| **功能完整** | **优质问答回流知识库** | 🔴 **缺失** | 无 reflow / exemplar |
| 功能完整 | FAQ 标准问答库 | 🔴 缺失 | 无 Q-A pair 模型 |
| 功能完整 | 文档版本管理 | 🟡 字段空壳 | `document.py:60` 有 version_info 无逻辑 |
| 功能完整 | 标签 / 分类体系 | 🟡 仅空间级自由标签 | `space_schema.py:43`；KB/文档无标签 |
| 功能完整 | 知识图谱 / GraphRAG | 🔴 缺失 | 无实体抽取 |
| **功能完整** | **通知系统接线** | 🔴 **空转** | 7 种 NotificationType 0 业务调用 |
| 权限治理 | 空间级 RBAC | 🟢 | `permission_service.py` |
| 权限治理 | 文档级权限 | 🟡 预留未落地 | `space_member.py:54` custom_permissions 未使用 |
| 权限治理 | 操作审计日志 | 🟢 结构化落库 | `space_audit_log.py` + `audit_service.py` |
| **权限治理** | **审计日志合规留存** | 🔴 **删空间级联删日志** | `space_service.py:318` |
| 权限治理 | 数据隔离（ES 分索引） | 🟢 | `elasticsearch_client.py:96` |
| **权限治理** | **AI 接口限流** | 🔴 **常量定义了未挂载** | `rate_limit.py:215`；ai_chat/qa/search 路由无装饰器 |
| 权限治理 | PII 检测 / 脱敏 | 🔴 仅 agent 用、无中文 PII | `redact.py` 调用点 2 处，知识库链路未覆盖 |
| 权限治理 | 删除补偿 / GC | 🟡 失败仅 warning | `document_service.py:591` 无重试 |
| 产品体验 | 流式对话交互 | 🟢 | `ChatView.vue:313` |
| **产品体验** | **首页「搜索即入口」** | 🔴 **假入口** | `HomeView.vue:28` 输入框不可输入 |
| **产品体验** | **引用展示 UI** | 🔴 **缺失** | `ChatView.vue` 无 citation 渲染 |
| 产品体验 | 文档在线预览 / 命中高亮 | 🔴 仅下载 | `DocumentDetailView.vue` 无原文渲染 |
| 产品体验 | 反馈按钮 UI | 🔴 仅复制 | `ChatView.vue:110` |
| 产品体验 | Onboarding 引导 | 🔴 缺失 | 无引导库 |
| 产品体验 | 暗色主题 / i18n | 🔴 全缺 | 无 vue-i18n / isDark |
| 产品体验 | 移动端 | 🟡 桌面优先 | 无移动布局 |

**统计**：37 项能力中 🟢 12 / 🟡 9 / 🔴 16（P0-1 QA 接检索由 🔴 转为 🟢 完整 RAG 管道，P0-3 拒答由 🔴 转为 🟡 分级拒答就位，查询改写由 🟡 转为 🟢 已接入 QA，基线更新于 2026-07-04）。红色集中在「回答质量」「功能闭环」「产品体验入口」三个块——恰好是企业知识库的核心。

---

## 三、改进路线图（按优先级）

### 优先级定义

- **P0 基础可信**：不做这些，产品就不是「知识库」（假 RAG、无引用、无防滥用）。
- **P1 反馈与自进化**：做了才能让知识库「越用越好」（反馈闭环、知识回流、通知接线）。
- **P2 治理与合规**：企业/政企采购的硬门槛（细粒度权限、审计留存、PII、删除治理）。
- **P3 体验提升**：决定留存与口碑（首页、预览、引导、主题、图谱）。

---

### P0 — 基础可信（最高优先级）

#### P0-1 打通 QA → 知识库检索的 RAG 链路 ⭐⭐⭐

> **🟢 落地进展（2026-07-04）：完整 RAG 管道已落地，包含查询改写、Grade-Retry 自评估、检索链路 SSE Trace。**
> - ✅ **会话级自动 RAG**：SessionConfig 新增 `auto_rag` / `space_id` / `kb_ids` 等 10 个字段，配置单一来源（从会话表读，前端不传）。
> - ✅ **查询改写（4 策略）**：`QueryRewriter` 支持 COMPLETION / SYNONYM / HYDE / DECOMPOSE，DECOMPOSE 多子查询合并去重 + 编号清洗。
> - ✅ **Grade-Retry 自评估**：`GradeRetrier` 检索后 LLM 打分（1-10），不通过则换 mode + 降阈值重检索，最多 2 次重试。
> - ✅ **检索链路 SSE Trace**：`rewrite` / `search` / `grade` 条目经 SSE 透传前端 `RetrievalTrace`，含降级标记与 note 区分。
> - ✅ **分级拒答**：`refusal_enabled` + `score_threshold` 控制，拒答关时不做分数过滤。
> - ✅ **工作台收敛**：`WorkspaceLayout.vue` 频道分组为「核心（Chat / Agent）+ 更多（深度研究 / 技能广场 / ClawMate）」。
> - ⏳ **剩余**：① 响应增加 `sources` / `answer_status` / `confidence`（→ 与 P0-2 引用 UI 联动）；② 前端拒答态差异化展示。
> - **注意**：前端控制已简化为仅联网开关（`enable_web_search`），RAG 细节统一从会话配置读取，用户可在会话设置面板中配置。

**目标**：智能问答真正基于知识库回答，而不是 LLM 凭空生成。

**现状**：`ai_chat_service._prepare_chat` 已完成完整 RAG 管道改造（查询改写 → 检索增强 → Grade-Retry → 分级拒答 → Trace）。`QAResponse` 仍无 sources 字段，待 P0-2 联动。

**下一步**：sources 结构化返回 + 前端引用展示（P0-2）。详见 [`docs/REFACTOR-qa-rag-pipeline.md`](./REFACTOR-qa-rag-pipeline.md)。

---

#### P0-2 引用溯源 UI（回答内联角标 + 可点击跳转）⭐⭐⭐

**目标**：用户能看到「这句话来自哪篇文档第几页」，并能点开原文。

**现状**：`ChatView.vue` 无任何引用渲染；`SearchView.vue:1110` 检索结果 `cursor: default` 不可点击；`DocumentDetailView.vue` 只能下载不能在线看。

**方案**：
1. 后端在生成回答时，prompt 要求 LLM 在陈述处标注 `[1][2]` 角标，并将角标序号映射到 `sources[i]`（按出现顺序编号）。
2. 前端 `MarkdownRenderer` 后处理：把 `[1]` 渲染为可点击的角标气泡，hover 显示来源文档名 + 得分，点击打开引用抽屉/跳转文档预览对应分块。
3. 回答底部固定「来源 N 篇」可展开列表。

**涉及文件**：
- 后端：`qa_prompts.py`（强化 citation prompt）、`ai_chat_service.py`（角标映射逻辑）
- 前端：
  - `frontend/src/utils/markdown.ts` — 角标 token 解析
  - `frontend/src/components/.../MarkdownRenderer.vue` — 角标渲染 + 引用气泡
  - `frontend/src/views/chat/ChatView.vue` — 来源列表
  - 新增 `CitationPopover.vue` 组件

**验收标准**：回答中每个角标都能 hover 出来源、点击跳转到对应文档分块并高亮。

---

#### P0-3 防幻觉拒答机制 ⭐⭐

**目标**：知识库找不到依据时，明确说「未找到」而不是编造。

**现状**：只有 `qa_prompts.py:26` 提示词软约束，无代码级判断。

**方案**：
1. 检索后判断 Top1 得分，**低于阈值（如 0.35，可配）直接拒答**，返回固定兜底话术 + 空 sources，跳过 LLM 调用（省成本）。
2. 可选：LLM 生成后用 faithfulness 校验（复用 `evaluation` 模块的 `generation_evaluator.py` 的 faithfulness 逻辑），矛盾则降级提示。
3. 响应里返回 `confidence` / `answer_status`（answered / not_found / low_confidence），前端差异化展示。

**涉及文件**：
- `ai_chat_service.py` — 阈值拒答分支
- `qa/schemas/qa.py` — `answer_status` 字段
- 复用 `backend/src/features/evaluation/services/generation_evaluator.py`
- 前端 `ChatView.vue` — 拒答态展示

**验收标准**：问知识库无关问题时返回「未找到」而非编造；问得着时正常回答。

---

#### P0-4 AI 接口限流挂载 ⭐⭐

**目标**：堵住成本与滥用风险（LLM 调用几乎不受限）。

**现状**：`rate_limit.py:215` 定义了 `CHAT 30/min / QA 30/min / SEARCH 30/min / UPLOAD 10/min` 等常量，但 `ai_chat_routes.py` / `qa_routes.py` / `search_routes.py` / `document_routes.py` **均未挂载 `@limiter.limit`**，实际只靠默认 100/min 兜底。

**方案**：把已定义的常量逐一挂到对应路由：
- `ai_chat_routes.py` → `RateLimits.CHAT`
- `qa_routes.py` → `RateLimits.QA`
- `search_routes.py` → `RateLimits.SEARCH`
- `document_routes.py`（上传）→ `RateLimits.UPLOAD / BATCH_UPLOAD`
- `deep_research/routes.py` → `RateLimits.DEEP_RESEARCH`

**涉及文件**：上述 5 个 routes 文件。

**验收标准**：单用户超阈值时返回 429；默认配额可在 YAML 配置。

---

### P1 — 反馈闭环与知识自进化

#### P1-1 用户反馈采集（👍👎 / 纠错）⭐⭐

**目标**：收集「回答是否有用」，作为后续优化的核心数据。

**现状**：qa 模块 feedback 0 命中；`QuestionAnswer.extra` JSON 字段（`question_answer.py:43`）注释预留了反馈但无人写入；前端 `ChatView.vue:110` 只有复制。

**方案**：
1. 新增 `qa_message_feedback` 表（或直接用 `extra` JSON）：message_id / user_id / rating(good/bad) / correction_text / created_at。
2. 新增接口 `POST /api/v1/qa/messages/{id}/feedback`。
3. 前端回答下加 👍👎 按钮，点踩弹出「纠错/补充」输入框。

**涉及文件**：
- 后端：新增 `qa/models/message_feedback.py`、`qa/api/routes.py` 加接口、`qa/services/`、`startup_manager.py` 注册
- 前端：`ChatView.vue`、`api/types.ts`、`api/chat.ts`、新增 `FeedbackBar.vue`

**验收标准**：能提交评分与纠错文本；后台能查询某回答的反馈。

---

#### P1-2 优质问答回流（标记范例 → 沉淀知识）⭐⭐

**目标**：让知识库「越用越厚」，而不是单向消耗。

**现状**：无 reflow / exemplar 机制；系统只读不写知识。

**方案**：
1. 在优质回答（人工标记 👍 或多用户好评）上提供「加入知识库」操作，把 Q-A 转写成一条**结构化问答文档**入库（走现有文档管道，或新增 FAQ 类型）。
2. 下次相似问题命中时优先返回该标准答案（与 P1-4 FAQ 协同）。

**涉及文件**：
- 后端：`qa/services/` 新增 reflow 逻辑、复用 `document_service` 入库、`knowledge_space/api/document_routes.py`
- 前端：`ChatView.vue`「加入知识库」按钮、选择目标 KB 的弹窗

**验收标准**：标记的优质问答能在目标 KB 检索到。

---

#### P1-3 通知系统接线（消灭空转）⭐⭐

**目标**：`notification` 模块已建好但 0 业务调用，是死代码，接通它。

**现状**：`NotificationType` 7 种类型（`notification.py:12-20`）除枚举定义外**全仓无业务调用**；文档处理完成、深度研究完成、技能审查结果都不通知。

**方案**：在关键事件点注入 `NotificationService.send_notification()`：
- 文档处理完成 → `document_service` 处理管道结束处（`document_ready`）
- 深度研究完成 → `deep_research_service` 报告生成后（`research_done`）
- 空间邀请 → `member_routes.py` 邀请成功后（`space_invite`）
- 技能审查结果 → `skill_marketplace_service`（`skill_review`）

**涉及文件**：上述 4 个 service/routes。

**验收标准**：对应事件发生时，用户收到站内通知（按偏好决定是否邮件）。

---

#### P1-4 FAQ 标准问答库 ⭐

**目标**：企业 20% 问题占 80% 流量，FAQ 直接命中省 LLM 成本与延迟。

**现状**：无 Q-A pair 模型，所有知识走「文档→切片→向量化」。

**方案**：
1. 新增 `kb_type` 区分文档库 / FAQ 库；FAQ 库存储标准 (question, answer) 对。
2. FAQ 库的检索走「问题向量」精确匹配，命中即返回标准答案，绕过 LLM。
3. 与 P1-2 联动：优质问答回流默认进入 FAQ 库。

**涉及文件**：
- 后端：`knowledge_base.py` 加 `kb_type`、新增 FAQ pair 模型与 service、`search_service.py` FAQ 命中分支
- 前端：KB 创建时选类型、FAQ 管理界面

**验收标准**：FAQ 库的命中问题 1 跳返回标准答案、无 LLM 调用。

---

### P2 — 治理与合规

#### P2-1 文档级权限（落地 custom_permissions）⭐

**现状**：`space_member.py:54` 的 `custom_permissions` JSON 字段已预留但全仓无人写入；文档权限完全继承空间，无法「单篇文档对部分人不可见」。

**方案**：定义 `custom_permissions` 结构（如 `{"doc_ids_visible": [...], "doc_ids_hidden": [...]}` 或标签式 ACL），在 `permission_service.py:_check_custom_permission` 接入文档级判断，检索时在 ES 查询侧补 `doc_id` 过滤。

**涉及文件**：`permission_service.py`、`document_service.py`、`search_service.py`（检索过滤）、前端成员管理 UI。

**验收标准**：可对成员设置文档级可见/不可见，检索不返回无权文档。

---

#### P2-2 审计日志合规留存 ⭐⭐

**现状**：`space_service.py:318` 删空间时级联删审计日志（违反合规）；`user` 模块登录/登出/Token 刷新未接入审计。

**方案**：
1. 删除空间/KB 时**保留**审计日志（迁移到归档表或仅软删），禁止物理删。
2. `auth_service` 登录/登出/Token 刷新/密码重置接入 `AuditService`。
3. 文档/数据导出操作加审计。

**涉及文件**：`space_service.py`、`knowledge_base_service.py`、`auth_service.py`、`user_routes.py`。

**验收标准**：删空间后审计日志仍可查；登录有审计记录；满足 1 年留存。

---

#### P2-3 PII 检测与脱敏（中文）⭐⭐

**现状**：`redact.py` 只覆盖英文 API Key 格式、只用于 agent；知识库上传 / RAG 链路完全不脱敏；中文 PII（身份证 / 手机 / 银行卡）0 覆盖。企业文档常含 PII，明文进 ES + 进 LLM 上下文是数据泄露风险。

**方案**：
1. 扩充 `redact.py`：加中文身份证、手机号、银行卡、邮箱正则 + 可选 NER 模型。
2. 文档入库切片后、写 ES 前做 PII 扫描，命中按策略（脱敏 / 拦截 / 标记）处理。
3. LLM 回答输出做脱敏二次校验。

**涉及文件**：`shared/utils/redact.py`、`document_service.py`（入库钩子）、`ai_chat_service.py`（输出钩子）。

**验收标准**：含身份证的文档入库后 ES 中为脱敏态；回答不回显原文 PII。

---

#### P2-4 删除补偿与 GC ⭐

**现状**：ES / MinIO 删除失败仅 warning（`document_service.py:591`）；软删数据永久残留无硬删任务。

**方案**：
1. 删除失败的 ES/MinIO 资源写入补偿队列（复用 `shared/mq/` arq Worker），后台重试。
2. 定期 GC 任务清理 `deleted_at` 超过 N 天的软删记录及其残留物理数据。

**涉及文件**：`shared/mq/`、新增 cleanup worker、`startup_manager.py` 注册定时任务。

**验收标准**：删除失败后能在后台最终一致清理；软删超期数据被硬删。

---

### P3 — 产品体验提升

#### P3-1 首页「搜索即入口」（修复假入口）⭐⭐

**现状**：`HomeView.vue:28` 输入框不可输入（只是跳转按钮），真检索埋在「空间→检索」三层菜单后，与「企业知识库」诉求严重错位。

**方案**：
1. 首页输入框做成**真·全局搜索**：输入即检索「我有权限的所有空间/KB」，结果分「文档命中 / 问答直达」两类。
2. 顶栏 `AppHeader.vue` 加全局搜索框（复用现有 `SearchBar.vue` 组件，当前竟没被任何地方用）。
3. 一键发起「基于命中文档的问答」。

**涉及文件**：`HomeView.vue`、`AppHeader.vue`、`SearchBar.vue`、新增全局检索接口（带权限过滤）。

**验收标准**：首页/顶栏可直接搜全库并直达问答。

---

#### P3-2 文档在线预览 + 命中高亮 + 分块跳转 ⭐⭐

**现状**：`DocumentDetailView.vue` 无原文渲染只能下载；`SearchView.vue:1110` 检索结果不可点击；命中关键词无高亮。

**方案**：
1. PDF / DOCX 接入在线预览（pdf.js / 服务端转 HTML）。
2. 检索结果卡可点击 → 打开文档预览 → 自动滚动到命中分块 + 高亮关键词。
3. 与 P0-2 引用跳转复用同一预览组件。

**涉及文件**：`DocumentDetailView.vue`、`SearchView.vue`、新增预览组件、后端可能需要原文渲染接口。

**验收标准**：从检索结果 / 引用角标能跳转到文档原文对应位置并高亮。

---

#### P3-3 Onboarding 新手引导 ⭐

**现状**：无任何引导；空状态只是静态占位。

**方案**：接入 `driver.js` / `vue-tour`，做「建空间→传文档→发起问答→看引用」4 步首次引导；空状态加「立即创建」CTA。

**涉及文件**：新增引导 composable、`HomeView.vue` / `ChatView.vue` 触发点。

---

#### P3-4 暗色主题 + i18n + 移动端 ⭐

**现状**：0 暗色、0 i18n、移动端桌面优先。

**方案**：
- 暗色：Element Plus dark + CSS 变量切换，`UserProfileView` 加主题偏好。
- i18n：接入 `vue-i18n`，先抽离核心文案，Element Plus 配中文 locale。
- 移动：顶栏汉堡菜单、抽屉式会话列表、输入区响应式。

**涉及文件**：`assets/main.css`、`main.ts`、`UserProfileView.vue`、各布局组件。

**验收标准**：可切暗色；Element Plus 组件语言一致；手机可用。

---

#### P3-5 知识图谱 / GraphRAG（高投入，可选）⭐

**现状**：无实体抽取 / 关系图谱。

**方案**：文档入库时抽取实体与关系（LLM 或 NER），存图结构，检索时叠加图遍历，提升「A 依赖哪些 B」类关系问答。

**说明**：投入大、收益依赖场景，建议排在 P0-P2 之后，且仅当有明确关系推理需求时做。

---

## 四、关键技术方案深入：P0-1 RAG 链路改造

这是整个路线图的基石，单独展开数据流。

### 改造前（现状）

```
用户提问
  → ai_chat_service.chat()
  → 取历史消息拼上下文（无检索）
  → LLM 裸生成
  → 返回 {content, role}          ← 无 sources、无拒答
```

### 改造后（目标）

```
用户提问
  → ai_chat_service.chat()
  ├─ 会话是否绑定 KB？
  │    ├─ 否 → 走原 LLM 对话（保持现有能力）
  │    └─ 是 ↓
  ├─ SearchService.search(space_id, kb_ids, query, mode=content_hybrid,
  │                        rerank=True, query_rewrite=hyde)
  │    → 命中 Top-K chunk
  ├─ 置信度判断：Top1.score < threshold？
  │    └─ 是 → 返回 {answer_status: not_found, sources: []}，跳过 LLM
  ├─ 命中 chunk 拼入 prompt 上下文 + 要求 LLM 标注 [1][2] 角标
  ├─ LLM 生成（流式）
  ├─ 角标 → sources 序号映射，附 document_id/chunk_id/page/score
  └─ 返回 {content, sources, answer_status, confidence}
```

### 数据契约

```python
# backend/src/features/qa/schemas/qa.py
class SourceRef(BaseModel):
    document_id: int
    document_name: str
    chunk_id: str
    page: int | None
    score: float
    snippet: str           # 截断的命中片段

class QAResponse(BaseModel):
    content: str
    role: str
    sources: list[SourceRef] = []
    answer_status: Literal["answered", "not_found", "low_confidence"] = "answered"
    confidence: float | None = None
    extra: dict | None = None
```

### 注意点

- **会话检索范围**：现有 qa session 模型需补「检索范围」（space_id + kb_ids），否则无从检索。建议在创建会话时指定，支持多 KB。
- **流式兼容**：`sources` 在流式场景需在首个 SSE 事件（或专用 `meta` 事件）下发，再流式推送 content。
- **成本控制**：默认 Rerank 关、HyDE 关，管理员可开；拒答分支直接省掉 LLM 调用。
- **复用优先**：检索能力全部复用 `search_service.py`，不另起实现。

---

## 五、里程碑建议（分阶段交付）

| 里程碑 | 范围 | 价值 | 预估 |
|--------|------|------|------|
| **M1 可信问答** | P0-1 + P0-2 + P0-3 + P0-4 | 产品真正成为「知识库」，回答可信可溯源 | 3-4 周 |
| **M2 反馈与进化** | P1-1 + P1-2 + P1-3 + P1-4 | 知识库自我增长，通知不再空转 | 3-4 周 |
| **M3 合规治理** | P2-1 ~ P2-4 | 满足企业/政企采购合规门槛 | 3-4 周 |
| **M4 体验跃迁** | P3-1 + P3-2 + P3-3 | 首页可用、预览闭环、引导到位 | 2-3 周 |
| **M5 打磨** | P3-4 + P3-5（按需） | 暗色/i18n/移动、可选图谱 | 2-3 周 |

> 建议先做到 **M1 + M2** 即可对外宣称「企业智能知识库」；M3 是 toB 采购必经；M4-M5 是体验拉齐。

---

## 六、风险与权衡

| 风险 | 说明 | 应对 |
|------|------|------|
| **范围蔓延** | 功能铺得广，容易每个都做半截 | 严格按 P0→M1 收敛，新需求必须服务主线 |
| **RAG 改造影响现有用户** | P0-1 改变 QA 行为 | 未绑定 KB 的会话完全保留原行为，灰度可配 |
| **检索延迟上升** | 接入检索+rerank+hyde 会增加首字延迟 | 默认关 rerank/hyde；FAQ 命中短路；拒答短路省 LLM |
| **LLM 成本** | RAG 上下文更长 | 拒答短路 + FAQ + 缓存相同问题 |
| **i18n / 暗色工作量大** | 文案遍布各 .vue | P3 再做，先借 M1-M3 立住核心 |
| **虚假宣传风险** | 首页「可溯源」目前不成立 | P0-2 上线前临时改文案，避免过度承诺 |

---

## 七、下一步

1. 评审本路线图，确认 P0 范围与里程碑。
2. 将 P0-2 ~ P0-4 拆为具体开发任务（建议用任务系统逐项跟踪）。
3. P0-1 完整 RAG 管道已落地（会话级自动检索 + 查询改写 + Grade-Retry + Trace + 分级拒答），下一步推进 P0-2 引用 UI 与 sources 结构化返回。

---

*文档基线日期：2026-06-15，基于当次源码核实。后续代码演进后需同步复核「现状」列。*
*更新记录：2026-06-15 — P0-1 开关式先行版落地（QA 接检索 🟡）、工作台收敛为 Chat+Agent 两种核心模式，已同步更新「现状」列与 P0-1 章节。*
*2026-07-04 — P0-1 完整 RAG 管道落地（查询改写 + Grade-Retry + Trace + 分级拒答），QA 接检索由 🟡 转为 🟢、拒答由 🔴 转为 🟡、查询改写由 🟡 转为 🟢，已同步更新能力矩阵与 P0-1 章节。*
