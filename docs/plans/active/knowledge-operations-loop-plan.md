# 知识运营闭环开发计划（KB-OPS Loop）

> **设计依据**：[`docs/knowledge-space/process/knowledge-operations-loop-design.md`](../../knowledge-space/process/knowledge-operations-loop-design.md)（痛点 → 归因模型 → 回路 → 路线图）。
> **计划性质**：执行计划，按批次拆解到文件级改动点与验收标准，可直接入 worktree 开发。
> **基线日期**：2026-10-01，现状结论基于当日源码核实。

---

## 零、现状核实结论（计划的前置事实）

| 集成点 | 现状 | 对计划的影响 |
|--------|------|-------------|
| `sources` / `answer_status` / `confidence` | 🟢 已进 `ChatMessageResponse`（`qa/schemas/ai_chat.py:65-67`），`ai_chat_service` 全链路产出（`_prepare_chat` 产出 `ChatPrep.sources/answer_status`） | 设计文档「P0-2 未落地」的前置警告**只对前端引用 UI 成立**，账本的后端数据源已就绪 |
| 反馈链路 | 🟢 前后端已通：`POST /message/{id}/feedback`（`qa_routes.py:142`）+ `qa_message_feedback` 表（含 space/kb 冗余维度） | 反馈**不重复落账本**，聚合视图直接读该表（设计文档 §八 已定） |
| eval 引擎 | 🟢 `engines/eval/` 四评估器齐备，无编排层 | 批次 C 是纯编排开发 |
| Document 模型 | 🟡 纯文件元数据（`document.py`），无 owner/review/lifecycle 字段；有 `_run_schema_migrations` 幂等补列钩子（无 Alembic） | 批次 B1 走 startup 补列钩子，不走迁移工具 |
| 通知系统 | 🟢 已接线多个业务点 | 批次 A2/B2 复用，需新增 NotificationType 枚举值 |
| 前端引用渲染 + 点击 | ❓ **未核实**（IMPROVEMENT 文档 2026-07-04 基线称 ChatView 无 citation 渲染，此后可能已变） | 批次 O2 开工前第一件事：核实引用 UI 现状 |

---

## 一、批次总览与泳道

```
泳道1（消费侧回路）:  O1 → O2 → A1 → A2 → C
泳道2（供给侧回路）:  B1 → B2        （B1 等 O1 合并后启动，避免 DB 模型/注册文件冲突）
收尾:                D              （依赖 A2 + B2 的账本与生命周期数据）
```

| 批次 | 内容 | 交付物 | 依赖 |
|------|------|--------|------|
| **O1** | 新 feature `knowledge_ops` + 事件账本 + 问答主链路埋点 | kb_events 表 + record_event 端口 + query/refusal/低置信落账 | 无 |
| **O2** | 查询信号补全：引用点击 + 会话内改写识别 | citation_click / query_reformulate 事件 + 事件查询 API | O1 |
| **A1** | 归因流水线（异步重放检索 + 四分归因） | arq worker + attribution 写回 | O2 |
| **A2** | gap 清单 + 管理视图 + 周报 | gap 聚合 API + 管理页 + 周报通知 | A1 |
| **B1** | 文档生命周期状态机 + 检索侧 active 过滤 | Document 新列 + 状态机 + ES 过滤 | O1（合并后） |
| **B2** | 替换建议 + 复审提醒 | 新版识别建议流 + 到期通知 | B1 |
| **C** | 质量基线（eval 编排） | 合成测试集 + 定时跑批 + 基线对比 | A2（flywheel 部分） |
| **D** | 治理增强 | 重复视图 + 矛盾建议队列 + 贡献者视图 | A2 + B2 |

**单点共享文件提醒**（多 agent 串行编辑，见根 CLAUDE.md）：`router_manager.py`、`startup_manager.py`、DB 模型、`shared/prompts/`、`*.example` 配置。每批次开工前 `git status` 确认基线干净。

---

## 二、批次详单

### 批次 O1：事件账本地基 ⭐ 一切的前提

**目标**：任意一次问答，能在账本里完整还原发生了什么；埋点失败不阻塞问答（失败方向安全）。

**新 feature 骨架** `backend/src/features/knowledge_ops/`：

```
knowledge_ops/
├── __init__.py
├── manifest.py
├── models/
│   ├── __init__.py
│   └── kb_event.py            # KbEvent 模型
├── repository/
│   ├── __init__.py
│   └── kb_event_repository.py
├── services/
│   ├── __init__.py
│   └── event_recorder.py      # record_event() 写入端口
├── api/
│   ├── __init__.py
│   ├── startup.py             # register_feature_initializer
│   └── routes.py              # 首批仅健康/占位，O2 起填事件查询
└── schemas/
    └── __init__.py
```

**KbEvent 模型要点**（概念 schema，字段以实现时微调为准）：

- `id, space_id(idx), kb_id(idx), event_type, user_id, session_id, message_id`
- `doc_id, chunk_id`（可空，文档类事件用）
- `query_text`（脱敏后）、`score`（float 可空）、`answer_status`（answered/refused/low_confidence）
- `attribution`（可空，A1 写回：content_gap / retrieval_failure / quality_decay / permission_boundary）
- `extra` JSON（扩展位）
- 索引：`(space_id, event_type, created_at)`、`(user_id, created_at)`
- 只追加不修改（无 Update 语义；attribution 写回是唯一例外，见 A1）

**`event_recorder.record_event()` 契约**：

- async，内部独立短事务（`begin_nested()` SAVEPOINT 规则）；**任何异常吞掉 + `log.warning`**，绝不向调用方传播——账本是旁路，不是主链路依赖；
- 入参即模型字段 + 脱敏在 recorder 内做（复用 `shared/utils/redact.py`，`query_text` 默认脱敏，可经配置关闭）。

**埋点位置**（`qa/services/ai_chat_service.py`）：

- `_prepare_chat` 返回 `ChatPrep` 后、响应返回前：`event_type=query`（记 answer_status、top1 score、sources 数量、检索模式）；
- 拒答分支（`refusal_on and not prep_sources`）：`event_type=query` + `answer_status=refused`（同一条事件，不单独建 refusal 类型，聚合按 answer_status 过滤——避免两种口径）。

**改动文件**：上述新骨架、`core/middleware/router_manager.py`、`core/middleware/startup_manager.py`、`qa/services/ai_chat_service.py`（埋点 2 处）、`qa/models/__init__.py`（如需注册关联）。

**技术要点**：

- `ai_chat_service` → `knowledge_ops.services.event_recorder` 为懒 import（函数内），维持 import 图无环（R1 门禁）；kb_ops 不 import qa services；
- 事件写入走 arq 还是同步写？**首批同步写**（单条 insert，延迟可忽略），避免为旁路引入队列依赖；后续量大再改异步（extra 里预留 replay 标记不需要，直接换实现不动契约）。

**验收标准**：

1. 绑定 KB 的会话问一句，`kb_events` 出现一条 `query` 事件，answer_status/score 正确；
2. 触发拒答（问库外内容 + 拒答开关开），事件 `answer_status=refused`；
3. 人为让 record_event 抛错（如断 DB mock），问答主链路正常返回；
4. query_text 含手机号/身份证样例，落库为脱敏态。

**测试**：`tests/features/knowledge_ops/test_event_recorder.py`（写入成功/异常吞掉/脱敏三组）、`tests/features/qa/` 补埋点回归（问答正常 + 事件存在）。

---

### 批次 O2：查询信号补全

**目标**：被动信号三类齐二（改写、点击；答后流失放 extra 观察，不做主动判定）。

**改动点**：

1. **引用点击埋点**：
   - 前置：**先核实前端引用 UI 现状**（`ChatView.vue` / `MessageList.vue` 是否已渲染 sources 角标）。若未渲染，本批次顺带补最小引用角标 UI（后端 schema 已就绪，纯前端工作）；
   - 后端：`POST /api/v1/qa/messages/{message_id}/citation-click`（body: chunk_id/doc_id），权限校验（消息属当前用户会话）→ `event_type=citation_click`；
   - 前端：引用角标点击时上报（fire-and-forget，失败静默）。
2. **会话内改写识别**（后端判定，前端零改动）：
   - 判定规则（保守，阈值可配）：同 `session_id` + 同 `user_id`，时间窗 T 内（默认 120s，YAML 可配）的连续两条 query 事件，归一化后字符 3-gram 相似度 ≥ 阈值（默认 0.5）→ 给后一条事件 `extra.reformulates = 前一条事件id`（不新建 event_type，聚合时按 extra 过滤——保持事件类型枚举最小）；
   - 实现位置：`knowledge_ops/services/`（如 `query_signal_service.py`），在 query 埋点落库后异步判定（不阻塞响应）。
3. **事件查询 API**（管理端基础）：
   - `GET /api/v1/kb-ops/events?space_id=&event_type=&since=&until=` —— `Depends(require_admin)` 或空间 admin 角色校验；**强制按权限域过滤**：非平台管理员只能查自己所属空间的事件（安全硬规则，防跨空间信息泄露）。

**验收标准**：

1. 同会话 120s 内问「退货政策是什么」再问「退货流程几天」，第二条事件带 reformulate 标记；间隔 10 分钟问两句相似话，**不**误标（正反用例）；
2. 点引用角标产生 `citation_click` 事件；
3. 空间 A 的管理员查不到空间 B 的事件（403 或空集，按语义定）。

---

### 批次 A1：归因流水线

**目标**：每条低置信/拒答事件获得四分归因之一，写回 `attribution` 字段。

**改动点**：

1. **arq worker** `knowledge_ops/tasks/attribution_worker.py`（经 `shared/mq/` 注册）：
   - 触发：query 事件 `answer_status in (refused, low_confidence)` 时入队（O1 埋点处顺手 enqueue，失败仅 warning）；
   - 逻辑（设计文档 §5.3 的落地）：
     a. 以**事件原始 user 权限**重放检索（同 query、同检索参数）→ 命中 → 归因 `permission_boundary`（存在但无权）；
     b. 以**空间管理员权限**（即忽略文档级限制，空间内全量）重放 → 命中但低分 → `retrieval_failure`；命中且过期/superseded 文档占比高 → `quality_decay`；
     c. 两路都无命中 → `content_gap`；
   - 写回事件行 `attribution`（唯一允许的 UPDATE，幂等：已有 attribution 不覆盖）。
2. **降级链**：重放检索依赖的 service 不可用时，attribution 留空 + worker 记 error 日志（失败方向安全：宁缺归因，不给错误归因）。

**技术要点**：

- 重放检索 import `knowledge_space` 的 SearchService 公共面（R2：走 services 公共类）；worker 里不 import qa 任何东西（数据从 kb_events 读）；
- 权限重放需要文档级权限过滤语义——若当前检索链路无检索时权限过滤（复用双层权限模型），**先落 content_gap/retrieval_failure/quality_decay 三分，permission_boundary 判定留 stub 并在代码注释与本计划标注**，待检索层权限接线后补（不阻塞主线）。

**验收标准**（四类至少各一正例 + 一不误伤反例）：

1. 问库内完全没有的内容 → `content_gap`；
2. 问库内有但切分/检索命不中的内容（构造生僻表述）→ `retrieval_failure`；
3. 把命中文档置为 superseded 后重放 → `quality_decay`；
4. 正常成功回答的事件**不**进归因队列（反例）。

---

### 批次 A2：gap 清单 + 管理视图 + 周报

**目标**：管理员五分钟内回答七问之第 1 问：「这周多少问题答不上来？top 10 是什么？」

**改动点**：

1. **聚合查询**（`knowledge_ops/repository/gap_repository.py` 或聚合 service）：
   - gap 清单：`attribution=content_gap`（含 refused 且未归因完成的兜底口径？**不定兜底**——只统计已完成归因的，清单页显示「待归因 N 条」独立计数，口径清晰）；
   - 按 `query_text 归一化聚类`（首批用精确归一化去重 + 频次排序，不引入语义聚类模型；语义聚类留 D 批次评估）；
   - 时间窗参数（本周/本月）；按 space 分桶。
2. **API**：`GET /api/v1/kb-ops/gap-report?space_id=&window=week`（权限同 O2 事件查询）。
3. **前端管理页**：`views/kb-ops/GapReportView.vue`（基础列表：频次、最近提问时间、归因分布、原话展示）+ 路由注册。驾驶舱大屏**不做**（防范围蔓延，列表先验证价值）。
4. **周报**：arq 定时任务（每周一上午，cron 可配）→ 聚合上周数据 → `NotificationService.notify`（新增 `NotificationType.WEEKLY_KB_OPS_DIGEST`，枚举值新增注意 notification 模块的枚举校验处同步）→ 站内通知 + WS 推送。邮件不做（通知系统现有渠道为准）。

**验收标准**：

1. 造 5 条不同 gap 事件（3 条同主题归一化后同类），清单页显示 2 个条目、频次 3+2；
2. 周报通知可达空间管理员，内容含 top 榜与待归因计数；
3. 无权限空间的数据不出现在任何视图。

---

### 批次 B1：文档生命周期状态机（泳道2 起点）

**目标**：上传新版后旧版不再被召回；存量文档（无字段）行为不变。

**改动点**：

1. **Document 模型加列**（`knowledge_space/models/document.py`）：
   - `lifecycle_status`（String(16)，默认 `active`；枚举 draft/active/superseded/archived 放模块级 `LifecycleStatus` 常量类）
   - `owner_id`（BigInteger FK users，nullable；**回填策略：startup 补列钩子里 `UPDATE documents SET owner_id = uploader_id WHERE owner_id IS NULL`**，幂等）
   - `effective_date`（DateTime，nullable，默认取 created_at 语义但不回填）
   - `review_cycle_days`（Integer，nullable；KB 级默认值放 knowledge_bases 表加列 `default_review_cycle_days`，文档可覆盖）
   - `next_review_at`（DateTime，nullable，idx）
   - `superseded_by_doc_id`（BigInteger，nullable）
   - 全部经 `_run_schema_migrations` 幂等补列钩子注册（复用既有 CONSTRAINT_MIGRATIONS 同位机制）。
2. **ES 检索侧过滤**：
   - chunk 写入 ES 时带 `lifecycle_status` 字段（管道写盘点位：`engines/document/pipeline/` 入 ES 处 + knowledge_space 的 chunk 入库适配层，**开工时先定位唯一写入点**）；
   - 检索过滤：`must_not [{ terms: { lifecycle_status: [superseded, archived] } }]`——**用排除式而非 must=active**，存量数据无该字段时 ES 行为是「missing 字段不被 terms 命中」→ 自动视为可召回，零回填（先写一个针对 missing 字段行为的集成测试钉死这个语义再上线）。
3. **状态机 service**（`knowledge_space/services/lifecycle_service.py`）：
   - `supersede(old_doc_id, new_doc_id)`：旧文档置 superseded + 记 superseded_by + **复用 wiki retract 原语下线旧 chunks**（ES 删除或标记，按 wiki-architecture 既有实现）；
   - `archive(doc_id)`、`reactivate`（误操作恢复，从 archived 回 active）；
   - 转换校验：draft→active→superseded→archived 单向为主，仅 archived→active 允许回退；非法转换抛 `BaseAPIError` 子类（`knowledge_space/exceptions.py`）。
4. **API**：文档列表按 lifecycle 过滤 + 单文档状态转换端点（空间 admin 权限）。

**验收标准**：

1. supersede 后旧文档 chunk 检索不召回（正例）；新上传正常文档（无 lifecycle 字段的存量 + 新写入的 active）召回不受影响（反例，防误杀）；
2. 重启后端二次跑补列钩子不报错（幂等）；
3. owner 回填后旧文档 owner_id = uploader_id。

---

### 批次 B2：替换建议 + 复审提醒

**目标**：回路 B 跑通——更新意图变检索现实。

**改动点**：

1. **新版识别（保守，只建议不自动）**：
   - 上传完成回调处（`knowledge_space` 文档 ready 后）触发判定：同 KB 内 `file_hash` 不同但 (a) 归一化文件名高度相似，或 (b) chunk 级高相似占比超阈值（可配，默认保守）→ 生成「疑似新旧版本」建议记录（`knowledge_ops` 新表 `kb_review_suggestions`：space/kb/old_doc/new_doc/suggestion_type/score/status[open/accepted/dismissed]）；
   - 建议仅通知 KB 管理员/文档 owner，不自动转换状态。
2. **「替换旧版」确认流**：建议 accept → 调 B1 `lifecycle_service.supersede()`；dismiss → 关闭建议。
3. **复审到期扫描**：arq 定时任务（每日）扫 `next_review_at <= now + 提前量(可配默认7d)` → 通知文档 owner（`NotificationType.REVIEW_DUE`）；过期超 30 天未处理 → 周报带出（不单独升级通知，防告警疲劳）；
   - 到期复审完成动作 = 文档详情页「确认复审」端点 → 重算 next_review_at（now + review_cycle_days）。

**验收标准**：

1. 上传同主题新旧两版 → 建议产生、accept 后旧版不召回（B1 联动）；
2. 两篇无关但名字相似的文档（构造）→ 建议不产生或可 dismiss（反例，防误报骚扰）；
3. 到期提醒送达 owner；「确认复审」后 next_review_at 正确顺延。

---

### 批次 C：质量基线（eval 编排）

**目标**：改切分/检索配置后能拿到「变好/变坏 X%」的数字结论；生产 gap 一键入测试集。

**改动点**：

1. **前置核实**（批次第一天）：`features/evaluation/` 现有结构与依赖边界（它 import 检索的方式、已有 API 面），编排层**扩展 evaluation feature** 还是放 knowledge_ops——判定标准：测试集与跑批若需深度耦合知识库配置，放 evaluation（它已是测评领域归属）；knowledge_ops 只消费其报告（R2 公共面）。
2. **合成测试集生成**：
   - 触发：KB 维度手动触发 + 文档批量入库完成后可选触发（配额可配：每 KB 首批上限 N 题，防 LLM 成本失控，YAML 暴露）；
   - 实现：从 chunks 采样 → LLM 生成 QA 对（prompt 进 `shared/prompts/` 注册表）→ 落 `evaluation` 测试集表（复用/扩展现有表结构）；
3. **跑批与基线**：
   - 定时跑批（arq，频率可配默认每周）+ 手动触发；跑批结果快照落表（时间、配置指纹、各指标分数）；
   - **配置指纹**：切分参数 + 检索参数 + 模型名的稳定 hash，用于对比「同指纹不同时间」与「不同指纹」；
   - 报告 API：最近两次同指纹对比（回归告警口径：关键指标下降超阈值 → 周报带出）；跨指纹对比（改配置后 A/B 结论）。
4. **flywheel**：gap 清单条目「加入测试集」按钮 → 以该 query 生成测试用例（检索命中验证型：入库修复后此 query 应能命中）→ 下次跑批自动覆盖。

**验收标准**：

1. 对演示 KB 生成 20 题测试集并跑批，得到基线报告；
2. 人为调坏检索参数（如 rerank 关闭 + 阈值调高）再跑，对比报告显示下降；
3. gap 条目入测试集后，补充文档 → 跑批该用例转绿（人工观察即可）。

---

### 批次 D：治理增强（收尾）

**目标**：七问之第 3、7 问可答；矛盾只进建议队列，永不自动删改。

**改动点**：

1. **重复文档视图**：
   - 精确重复：`file_hash` 同 KB 分组（纯 SQL，零成本）；
   - 近重复：同 KB 内 chunk 级高相似聚合（首批复用 ES more_like_this 或向量自检索，阈值保守；语义去重模型不引入）；
   - 视图仅展示 + 一键调起 B2 替换建议流，**不自动合并**。
2. **矛盾建议队列**：
   - 候选对生成：同 KB 高相似 chunk 对（similar 但非重复阈值带）→ LLM 判定语义矛盾（prompt 注册表）→ `kb_review_suggestions` 表复用（suggestion_type=contradiction）→ 人工裁决（accept 后动作仅是「通知两位文档 owner 人工对齐」，平台不做任何自动改写）。
3. **贡献者激励视图**：
   - 聚合：文档被引用次数（citation_click 按 doc_id 聚合）+ 支撑回答数（query 事件 sources 含该 doc 的次数，从事件 extra 或关联表取——**实现注意：O1 埋点要把 source doc_ids 存入事件 extra 或子表**，否则 D 批次无法回溯统计）；
   - 呈现：文档列表加「本月引用 N 次」列 + 个人中心「我的贡献」页。
4. **答后流失信号**（可选，最后做）：query 事件后 10 分钟内无后续互动标记 extra.abandoned，仅进周报统计，不做实时功能。

**验收标准**：

1. 上传两次同文件 → 重复视图显示 1 组；矛盾样例（两版政策数字不同）→ 建议队列出现、owner 收到通知；
2. 全程无任何自动删除/改写行为（代码审查项）；
3. 贡献者视图数字与事件账本对得上（抽样核对）。

---

## 三、横切约定（全批次生效）

1. **异常**：kb_ops 新业务异常继承 `BaseAPIError`，exceptions 顶层归位（`knowledge_ops/exceptions.py`），`__dict__` 显式声明 `http_status_code`（不依赖继承链——历史三连 bug 教训）。
2. **事务**：所有 repository 写操作 `begin_nested()` SAVEPOINT。
3. **安全**：事件/gap/建议所有查询接口强制权限域过滤；query_text 落库前脱敏（redact.py）；不新增任何绕过 `get_current_user` 的端点。
4. **测试策略**：每批次正反两用例回归（防案例特例化漂移）；当前开发机内存紧张期的既定约定——**静态审查代跑 + pytest 欠账记入任务清单事后补**（不作为跳过测试的理由，作为执行顺序约定）。
5. **配置**：所有新阈值（改写判定窗口/相似度、相似文档阈值、测试集配额、跑批频率）一律 YAML 配置化并在 `*.example` 模板暴露，代码零硬编码（通用补丁原则）。
6. **契约先行**：前后端并行的批次（O2、A2）先在后端 schema + 本计划内定死接口契约，前端再开工。
7. **提交纪律**：每批次至少按「骨架 / 模型+迁移 / 埋点 / API / 测试」拆多次原子提交；commit message 中文说明动机。

---

## 四、风险与开放问题

| 风险/开放问题 | 影响 | 应对 |
|--------------|------|------|
| 前端引用 UI 现状未核实 | O2 工作量浮动（可能连带做引用渲染） | O2 第一天核实；若需补 UI，按最小角标实现，完整引用抽屉另立项 |
| 检索层权限过滤尚未接线 | A1 的 permission_boundary 归因缺依据 | A1 先落三分归因，permission_boundary 留 stub（本计划已标注） |
| evaluation feature 依赖边界未核实 | C 批次编排层归属（evaluation vs kb_ops） | C 第一天核实后定，判定标准已写明 |
| 事件表增长（高频问答场景） | 查询变慢 | 首版 created_at 复合索引 + 仅追加；分区/归档策略推迟到有真实量级数据后决策（不过早设计） |
| `next_review_at` 依赖 KB 配置默认值 | B1 加列涉及 knowledge_bases 表 | 与 Document 加列同一批迁移钩子完成，保持原子 |
| LLM 判定成本（C 测试集生成 / D 矛盾检测） | 跑批成本 | 配额 + 频率全部 YAML 可配；默认保守（小配额、低频） |
| 多 agent 并行冲突 | 单点共享文件（router/startup/DB 模型） | 泳道1 与泳道2 错峰启动（B1 等 O1 合并）；共享文件改动窗口内其他批次避开 |

---

## 五、里程碑与验收映射

| 里程碑 | 批次组合 | 对应设计文档验收 |
|--------|---------|----------------|
| M1「账本在记」 | O1 + O2 | 阶段 O 验收：任意问答可完整还原 |
| M2「gap 闭环」 | A1 + A2 | 七问之 1、4（点踩有下文——反馈工单流在 A2 周报带出） |
| M3「生命周期」 | B1 + B2 | 七问之 3（超期文档清单）；回路 B 全通 |
| M4「质量基线」 | C | 七问之 5（上月 vs 本月对比数字） |
| M5「治理收口」 | D | 七问之 2、6、7 全部可答 → 七问全绿 |

**M2 完成即可对外讲「gap 闭环」差异化故事；M3 完成后「私有化 RAG × 知识运营」定位成立。**
