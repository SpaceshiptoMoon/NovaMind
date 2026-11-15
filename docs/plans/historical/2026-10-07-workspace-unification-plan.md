# 工作台统一重构方案：个人 Agent 单一对话面（前端优先、后端跟随）

> **状态（2026-10-07 回填）**：批1 已实施并合并 main（d659dcb 默认助手幂等开通 + d5f0cd3 三频道收敛为单一「对话」+ QA 历史转只读归档）；批2 进行中——5b6e596 已落知识检索管线吸收 + 会话级知识绑定 + 消息反馈埋点。批3/批4 未开始。
> **批4 部分落地（2026-10-07 晚）**：清退三提交已并 main——992e9b7（NULL 空间研究行读取面修复）、9b77661（web 研究写入端点 POST+WS 与 QA 对话端点 /ai-chat/chat+/ws 清退，ai_chat 保留 agent 复用的附件/模型/健康端点；通知 link 统一指对话页）、2381ce1（前端 ResearchView/ResearchHistoryView/ChatView/ChatArchiveView 四视图 + chat/qa 组件链 + research/chat store/api 全删，/research/* redirect 对话页）。另有 599323d（编辑洗 extra_config 改 merge 语义）、93d5081（OpenAPI+文档）、98986ad（通知断言）、5f552d9（E2E 发现 redirect 层级错误，workspace 子树内补 /research/* 与 /chat/archive redirect）。OpenAPI 基线已刷新。**未做**：research 工具的计划确认桥接（PlanFeedbackRegistry 服务层已保留待接）；qa 三表与 research_sessions 数据保留未写入收口已达成。
>
> 2026-10-07 起草。目标：把工作台「AI 对话（QA）/ 智能体（Agent）/ 深度研究（Research）」三个平级入口，
> 收敛为行业标准形态——**一个聊天界面 + 输入框能力开关**，QA 与 Research 降级为能力/模式，不再是入口。
>
> 行业依据（2026-10 调研）：ChatGPT/Claude/Gemini/Perplexity/Kimi/Coze/Dify/Glean 无一例外均为
> 「单一对话面 + 输入框菜单/开关表达能力差异」；GPT-5 与 Kimi 已走到「模型自主决定是否检索」，
> 手动开关仅作覆盖。三入口平级的布局在市面上没有同类。

## 0. 设计原则

1. **入口和会话归一，后端编排允许分层。** 前端只有一个聊天面、一份会话历史；后端 QA 检索管线、
   research 引擎保留为独立编排层，但统一挂在 agent 会话模型与工具体系之下。
2. **检索决策权归模型**（终态）：要不要查库、查哪个空间由模型调 `KnowledgeSearch` 工具决定；
   用户侧「知识库范围」作为工具约束（软引导 via prompt + 硬过滤 via 参数），不是绕过模型的固定管线。
3. **前端先行可感知、后端跟随不返工。** 每一批都独立可合并，前端改动不依赖未落地的后端能力。
4. **旧数据不迁移。** QA 三张表（question_answers/qa_session_configs/qa_session_summaries）与
   research_sessions 原样保留，旧入口转只读。
5. 遵守 R1–R6：`features/agent` 已允许 import `features/qa` 公共面（ChatAttachmentRepository 先例）；
   检索管线复用走 `engines/rag` 与 `InstrumentedSearchService`，不复制实现。

## 1. 现状摘要（2026-10-07 摸底）

| | QA | Agent | Deep Research |
|---|---|---|---|
| 前端入口 | `/home/workspace/chat` → ChatView(495行) | `/home/workspace/agents(/:id/chat)` → AgentWorkspaceView+AgentChatView(2544行) | `/home/workspace/research[...]` → ResearchView(1363行)+HistoryView |
| 前端 API | api/chat.ts + api/session.ts | api/agent.ts | api/research.ts |
| 后端 feature | qa（22 endpoint，AiChatService 1721 行） | agent（26 endpoint，AgentChatService 1698 行） | deep_research（6 endpoint，DeepResearchService 1505 行） |
| 会话存储 | question_answers（字符串 session_id） | agent_sessions/agent_messages/agent_tool_calls | research_sessions 单表 |
| 模型自主权 | 无（auto_rag 配置驱动固定管线） | 有（AgentEngine 工具循环） | 无（服务端状态机 + WS 事件） |
| 计划交互 | 无 | PlanningFlow（分步执行） | plan_feedback_registry（WS 挂起等确认） |

已有共享地基：三者共用 `SearchService` 族（agent 的 `host_knowledge_search.py` 与 research 的
`deep_research_service.py` 均构造 `InstrumentedSearchService`）；agent 已复用 qa 的附件仓储与阅读器；
QA 复用 `engines/rag`（QueryRewriter/GradeRetrier）与 `engines/agent`（sanitize）。

关键缺口：**agent 无「默认助手」概念**（`AgentService.get_agent_or_fail` 要求显式 agentId），
这是前端合一的第一硬前置。

## 2. 目标形态

```
侧边栏
└── 对话（唯一聊天面，基于 AgentChatView 改造）     ← 取代 chat / agents / research 三频道
    ├── 会话历史（统一一份，全部落 agent_sessions）
    └── 「默认助手」兜底 agent（无自建 agent 也可直接聊）

输入框能力区（对齐 ChatGPT「+」菜单 / Kimi 开关 / Perplexity 模式选择器）
├── [+] 附件（复用现有 chat_attachments）
├── [模型] 用户模型选择（现 qa 的 llm_model 语义）
├── [知识库] 全部空间 / 指定空间 / 关闭        ← 映射 KnowledgeSearch 工具约束
├── [联网] 自动 / 开 / 关                      ← 映射 WebSearch 工具约束
└── [模式] 快速回答 / 深度研究                  ← 深度研究 = research 工具化 + 计划确认卡片
```

### 能力映射表

| 现功能 | 统一后的表达 | 后端落点 |
|---|---|---|
| QA auto_rag + 会话库绑定 | 「知识库范围」开关 | KnowledgeSearch 工具吸收检索管线（批2） |
| QA 查询改写 / grade-retry / 拒答 / 阈值 | 工具内部质量保障，模型无感知 | 下沉进 `host_knowledge_search.py`（批2） |
| QA 反馈（点赞点踩）/ 引用点击 | 消息级反馈 + 工具调用引用，埋点语义不变 | agent_messages 反馈表 + kb-ops EventRecorder（批2） |
| QA 附件 | 附件按钮（本就共享） | 不动（批1 即可用） |
| Research 独立页面/会话 | 「深度研究」模式开关 | research 引擎包装为 agent 工具（批3） |
| Research 计划确认卡片 | 对话流内计划确认（对齐现 ResearchPlanCard 交互） | plan_feedback 桥接到 agent 事件流（批3，先 auto-approve） |
| Agent 管理/编排 | 「智能体」收进设置页入口（不再是对话频道） | 不动（批1 仅前端导航调整） |

## 3. 分批实施

### 批1｜前端合一 + 默认助手（最小后端前置）

**后端（最小改动，~1 天）**
- `AgentService.ensure_default_agent(user_id)`：每用户内置「个人助手」agent 定义（幂等，
  `extra_config.is_default=true` 标记，enabled_tools 含 knowledge_search/web_search/attachment/memory）。
- 路由：`GET /api/v1/agent/default` 返回（必要时自动开通）当前用户默认助手；manifest 以 RouterSpec 声明。
- 测试：默认助手幂等开通 + 无 agent 用户首聊链路。

**前端**
- `WorkspaceLayout.vue`：`allChannels` 三频道收敛为单「对话」频道；「智能体」入口移到侧边栏底部
  设置区（agent 管理仍可达，不再是聊天入口）。
- 路由 `router/index.ts`：`/home/workspace/chat` 改为解析默认助手 → 渲染统一聊天面；
  `/home/workspace/agents/:agentId/chat` 保留；research 路由保留但移出主导航。
- QA 旧会话：ChatView 改造为「历史归档」只读视图（从设置/归档入口进），api/chat.ts 只读消费。
- 统一聊天面复用 AgentChatView 现有 ReAct 渲染（PlanCard/工具块/TrajectoryList），不新写消息组件。

**验收**：浏览器实测（agent-browser）：无自建 agent 的新用户 → 直接进对话 → 发消息 → 工具循环正常；
旧 QA 会话可从归档查看；type-check / lint 全绿。

### 批2｜KnowledgeSearch 工具吸收 QA 检索管线

**后端**
- `features/agent/tool/builtins/host_knowledge_search.py` 扩展为检索管线全权入口：
  - 工具入参新增可选约束：`space_ids`（用户会话级知识范围）、`top_k`、`search_mode`；
  - 管线内部按序执行：查询改写（QueryRewriter，LLM 用当前 agent 会话模型，**修掉 qa 现状
    「改写固定用用户默认模型」的错位**）→ InstrumentedSearchService 检索 → grade-retry（可选，
    agent 级配置）→ 阈值过滤；引用/溯源结构随工具结果返回（agent_tool_calls.result 已可承载）；
  - 拒答语义变为工具结果声明 `insufficient_evidence`，由主模型决定如何向用户表达。
- 会话级知识绑定：`agent_sessions` 加 `extra_config`（无则 `_run_schema_migrations` 幂等补列），
  批1 的「知识库范围」开关读写此字段，工具调用时作为约束注入。
- 反馈与运营埋点：新增 `agent_message_feedbacks` 表（对齐 qa_feedbacks 语义）；
  citation_click 经 EventRecorder 继续落 kb_events，message 归属查 agent_messages。

**验收**：pytest 覆盖改写/降级/拒答三分支 + 约束传递正反用例；InstrumentedSearchService 埋点
不回退（kb-ops 账本继续收数据）。

### 批3｜输入框能力面板 + 深度研究工具化（先 auto-approve）

**前端**
- 统一聊天面输入框加能力区（知识库范围/联网/模式），写入会话 `extra_config`（经 agent session 配置接口）。
- research 进度事件透传渲染（复用现 ResearchView 的事件→消息映射组件逻辑）。

**后端**
- `features/agent/tool/builtins/research.py`：包装 `engines/deep_research/engine.py` 为长任务工具；
  批3 先 `auto_approve=True` 跑通（计划直接采纳），进度事件经 agent 事件流下发前端；
- 深度研究模式开关 = 会话配置提示模型「复杂课题优先调用 research 工具」，同时工具始终对模型可见。

**验收**：对话中发起研究 → 进度实时渲染 → 报告落 agent 消息流；research_sessions 不再新增写入
（批4 前双轨观察）。

### 批4｜交互确认 + 清退

- research 工具的计划确认桥接：工具在 plan 阶段挂起 → agent 事件流下发计划卡片 → 用户确认经
  既有 plan_feedback 通道回灌（对齐 ChatGPT「review and modify before research begins」）。
- 清退：ChatView 归档页下线改纯 API 只读；ResearchView/ResearchHistoryView 下线；qa 的
  ai_chat_routes 与 deep_research 的 WS 路由废弃；qa 三表与 research_sessions 保留数据不再写入。
- 文档同步：`docs/project-structure-navigation.md`、知识库导航文档、OpenAPI 基线刷新。

## 5. 开源架构参照（2026-10-07 调研）

**DeerFlow（字节）演化 = 本方案方向的直接佐证。** 1.x（main-1.x 分支）是固定五节点 LangGraph 研究图
（coordinator→planner→human_feedback→research_team→reporter，`src/graph/nodes.py` 承载全部角色）；
2.0（2026-02）ground-up rewrite 且官方声明与 1.x 零共享代码：唯一入口一张 `lead_agent` 图 +
11 层中间件链，深度研究降级为 SKILL.md 技能包（`/mnt/skills/public/research/SKILL.md`，渐进加载），
子任务经 `task` 工具动态派生 subagent（`max_turns` 上界 + 沙箱隔离 + 独立上下文），
plan 确认 = RunStore 持久化 interrupted 状态 + checkpoint 恢复。

其余平台关键模式：

| 平台 | 可借鉴点 |
|---|---|
| RAGFlow 0.20 | 「一核两皮」：同一套 Retrieval 实现既当 Workflow 固定组件、又当 Agent Tool（agent 决定何时调用）；QA=检索强制注入档，非独立产品 |
| Open WebUI | Tools（模型决定调）vs Functions/Pipes（必然执行的 inlet/outlet 过滤）——横切逻辑与模型工具在词汇层分离 |
| AnythingLLM | `@agent` 任意聊天内联激活；按查询预过滤工具/skill 集（token 省 80%） |
| LobeChat | 单一聊天面 + agent persona 商店 + 插件=function calling + RAG 挂助手配置 |

对本方案的落点修正：

- 批2 维持「一套检索核心（InstrumentedSearchService）两种暴露」——管线质量层（改写/grade/拒答）
  进工具内部，与 RAGFlow 同构，不复制实现。
- 批3 research 工具明确对齐 DeerFlow `task` 语义：迭代上界（复用 research 引擎现有 max 阶段数）、
  独立上下文、进度事件回流主对话流。
- 横切逻辑（sanitize/压缩/预算）确认走既有 ToolExecutor hooks / engines/agent 中间件，
  不新增图结构级编排（DeerFlow 2.0 中间件化先例）。
- 远期（不进本重构）：技能广场向 DeerFlow SKILL.md 式「按需加载能力包」演进；
  DeerFlow 的「编辑上一轮重放（checkpoint restore）」可作统一聊天面的后续交互增强。

## 6. 风险与协调

- **并行窗口冲突（高）**：另一窗口正在做 QA 聊天链路 E2E 与 SearchView/PlanCard 改动。本重构
  必须在独立 worktree 分支进行（`feat/workspace-unification`），批1 前先确认 QA E2E 批次已合并。
- **AgentChatView 2544 行**：批1 只做导航/路由级改造不拆文件；组件拆分留给后续独立重构，避免一批两事。
- **快速问答延迟回退**：agent 循环比 QA 单次生成多一轮工具决策。缓解：默认助手 system prompt 引导
  简单问题直接作答（agent 循环本就支持首轮不调工具）；不再为「不检索」保留第二条固定管线（Kimi 先例）。
- **kb-ops 数据连续性**：citation_click/检索埋点的 message 归属从 question_answers 切到
  agent_messages，账本口径需在批2 一并声明，历史数据按 session 维度区分来源。
- **用户配置哲学**（没选不兜底）：「知识库范围=全部空间」必须是用户显式选择，默认值进
  `.env.example`/配置模板暴露，不硬编码降质。
