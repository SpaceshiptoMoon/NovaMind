# 工作台剥离与知识服务定位转型（2026-11）

> 本文是 2026-11-15 完成的产品定位转型与大规模剥离的**决策记录与实施全档**：为什么做、做了什么、
> 怎么做的、最终成了什么样。供未来回溯决策动机、理解当前架构边界、或评估「重建对话能力」成本时阅读。
> 当前架构事实以本文「最终形态」一节与 `project-structure-navigation.md` 为准
> （数字为 2026-11-15 剥离完成时快照；11-16 起新增的 knowledge_ops/evaluation/agent_api
> 模块不在此列，现行以仓库实际为准）。

---

## 一、背景与动机

### 1.1 转型前的产品形态

转型前 NovaMind 是一个「双模块」产品：

- **知识空间（knowledge_space）**：面向企业运营人员的知识治理平台——多租户空间/知识库管理、
  全模态文档解析（PDF/Office/音频/视频/图片，DeepDoc 引擎）、切分与向量化、9 种模式的混合检索、
  自动 Wiki 生成、评测体系，以及 kb-ops 知识运营闭环（事件账本、失败归因、缺口清单、复审提醒、
  质量基线、治理视图）。配置复杂：KB 多模态开关、解析策略、切片参数、检索模式、ASR 链路……
  这些是「懂行的人」才能驾驭的深度能力，也是几个月深水区投入积累的**护城河**。
- **工作台（agent）**：面向大众用户的对话界面——单聊（助手对话）、绑定本地目录的本地项目模式、
  多成员协作对话（群聊头脑风暴）、助手管理与技能广场。入口是 `/home/workspace` 三分类侧栏。

两者共享一个应用、一个导航、一个用户体系。工作台侧的 agent 能力在转型前刚完成一轮高强度建设：
断连转后台续跑、工具目录按需加载（load_tools）、群聊编排器、审批持久化、记忆系统、MCP 客户端、
chat_service 架构收敛等。

### 1.2 冲突的暴露

定位问题是从一个具体的产品疑问开始暴露的：**工作台的三种会话类型（助手对话/本地项目/协作对话）
各自的价值是什么？** 顺着这个问题往下追问，暴露出三层冲突：

1. **两个「产品灵魂」在打架。** 工作台里「本地项目」是开发者写代码的工作模式（DeerFlow 式），
   「协作对话」是多 agent 头脑风暴——它们服务的不是「大众消费知识」，而是把工作台往**通用 Agent
   平台**方向推。于是整个产品同时想当「企业知识库的问答门面」和「通用 agent 工作台」，两个灵魂
   抢一个壳。这正是「看起来不搭」的根源：不是知识空间与工作台的受众分工有问题，而是工作台自身
   长偏了。

2. **供给侧配置泄漏到了消费侧。** 企业知识类产品的标准结构是「生产者—消费者」双层：运营人员在
   供给侧把知识治好（复杂度砍不掉），全员在需求侧极简消费（Glean / Dify / Coze / Confluence AI
   无一例外）。判断冲突的标尺是**大众是否被迫理解供给侧的复杂度**。转型前的工作台创建助手要勾工具、
   配 MCP、选模型、调记忆——这些是运营才该理解的事，实打实的泄漏。

3. **生产深、消费浅，闭环没咬合。** 知识空间是深水区投入，工作台的消费体验相对薄（一个聊天框），
   两个模块没有形成「运营建设 ← 反哺 → 大众消费」的往返，看起来像两个产品拼在一起。

### 1.3 备选方案的取舍

讨论过程中评估过三条路，最终取舍及理由如下：

| 备选方案 | 结论 | 理由 |
| --- | --- | --- |
| 收窄工作台为「知识消费面」（砍本地项目、降级协作对话） | 不够彻底 | 解决了灵魂打架，但「自家工作台 + 知识空间」仍是两个模块一个壳；且 agent 编排本身是同质化能力（人人都有），单靠它没有差异化 |
| 拆成两个应用：知识空间留 Web，工作台做成桌面客户端 | 否决 | 客户端只有两种活法：①连企业服务器 → 只是 Web 换壳，还给企业 IT 增加分发/审批/升级负担（企业软件交付标准是浏览器）；②只连本地文件 + 用户自己的 key → 重新发明 Cherry Studio/ChatBox，红海且知识空间的核心能力（解析/检索/质量运营）在客户端架构里根本用不上。为一个该砍的开发者向功能换整个交付形态，不值 |
| **知识空间服务化**：知识空间保留为独立产品，把检索能力经标准协议（MCP / OpenAI 兼容网关 / API）暴露出去，agent 对话产品整体剥离，对话由外部宿主（Claude Code、Cursor 等）承担 | **采纳** | 这是 Dify 知识库 API、Coze 开放接口、ragflow API 的成熟形态。差异化恰恰落在「agent 直接吃知识空间的深检索能力」——ragflow 有深检索没好对话，Coze 有好对话没深检索治理，NovaMind 两头都深，且对外输出后知识空间的客户面从「自家工作台用户」扩大到「任何 MCP 宿主」 |

还有一个关键事实支撑这个方向：**服务化出口的地基已经存在**。`agent_api` feature 在 kb-ops 批次中
已落地 MCP server（`kb_search` 检索工具，FastMCP stateless，权限链完整继承）、API key 门禁
（创建/吊销/脱敏）、OpenAI 兼容网关（`/v1/chat/completions`），且 dogfooding 闭环验证过。
转型不是从零建出口，而是「把已验证的出口确立为主定位，剥掉同壳的另一件产品」。

### 1.4 拍板结论

> **NovaMind = 知识空间独立服务**：运营人员在知识空间治好知识，任何 agent 宿主经标准接口用上知识。

用户对四个伴生模块逐一拍板：

- **skill（技能广场）**：随工作台剥离——「安装」概念硬绑 agent（安装 = 写 agent 的
  `enabled_tools` + system prompt 注入，FK 直指 `agent_definitions` 表），agent 走后无独立价值。
- **deep_research（深度研究）**：随工作台剥离——不依赖 agent 但唯一消费者是 agent 的 research
  工具，前端视图早已并入工作台，agent 走后无调用方、无 UI 入口。
- **app（简历中心）**：随工作台剥离——虽与 agent 零依赖，但用户选择彻底聚焦知识空间，一步到位。
- **evaluation / notification / agent_api**：保留——evaluation 被 knowledge_ops 硬依赖
  （quality_baseline、gap_to_testset）；notification 被 knowledge_space/knowledge_ops/user 等多处
  发送；agent_api 即新定位的对外出口主体。
- **agent_api 不改名**：名字带 "agent" 但实为知识 API 网关，改名牵连路由前缀 `/api/v1/agent-api`、
  表名 `agent_api_keys`、既有文档与用户凭证，收益为零。

---

## 二、剥离实施（第一阶段）

实施按「可独立验证的原子批次」推进，共 3 个 commit。

### 2.1 批次 1：后端源码剥离（commit `96a0fe76`）

**删除**（git rm，328 个文件，+7454/−78971 行）：

- `backend/src/features/{agent, skill, deep_research, app}/`
- `backend/src/engines/{agent, deep_research, resume}/`
- `backend/src/runner/`（本地工作区 runner 伴生执行器，硬连 agent runner WS）
- 对应测试目录：`backend/tests/features/{agent, skill, deep_research, app}`、
  `backend/tests/engines/{agent, deep_research, resume}`、`backend/tests/integration/test_agent_e2e.py`

删除前用 grep 全量复核了 8 个目录在保留代码中**零外部消费者**（skill/deep_research/app 的外部
引用只剩 3 个 core 装配点文件；engines.{resume,deep_research} 与 runner 无外部引用）。

**同步修改的 6 个装配点**（这是本批次最大的风险区——漏改任何一个都会让应用或全部测试崩）：

| 装配点 | 改动 | 不改的后果 |
| --- | --- | --- |
| `core/middleware/prompt_registration.py` | 删 5 个已删模块的 TEMPLATES import 与注册项（保留 knowledge_space/evaluation） | **conftest 的 autouse fixture 依赖它**——全部后端测试在收集阶段崩 |
| `core/middleware/exceptions.py` | 删 agent/app/deep_research/skill 异常处理器注册（保留 agent_api，且其 `/v1/*` 分流 handler 必须保持在全局 handler 之后注册） | 3 个走 `create_app()` 的测试崩（openapi 快照×2、runtime 诊断） |
| `core/middleware/startup_manager.py` | 删 agent 3 个 arq 任务、app resume 任务、`agent_mcp_manager` 关闭段（保留 evaluation 恢复、agent_api MCP 关闭） | 启动期 ImportError |
| `shared/prompts/templates.py` | 删 `AGENT_*`×3、`AGENT_ENGINE_*`×10、`RESUME_*`×15、`RESEARCH_*`×7、`SKILL_*`×2 枚举 | 提示词一致性门禁挂 |
| `core/authorization/app_codes.py` | `AppCode.ALL` 与 `GATED_APP_PREFIXES` 清空 | 门禁指向不存在的模块 |
| `engines/rag/modes.py` | docstring 去掉 engines/agent 提及 | 仅注释失实 |

**设计决策——应用门禁机制保留但清空条目**：`AppGateMiddleware` 是「管理员禁用某应用」的可见性
控制（deny-list），牵连 user feature 的 `user_disabled_apps` 表与 schema 校验。采取最小改动：
机制与表保留，`AppCode.ALL=[]`（空表 = 恒放行，语义安全），`test_app_access.py` 用 monkeypatch
注入临时门禁条目，保住中间件分流逻辑（403/WS 4403/fail-open）的回归防线。

**门禁白名单同步**（这些门禁对「白名单条目指向不存在的文件」零容忍，必须与删除同 commit）：
`test_repository_savepoint_gate.py` 删 8 条 agent/app 条目、`test_no_cross_feature_repository_imports.py`
删 chat_context_builder 与 skill 条目（agent_api 条目保留）、`test_batch5b_model_config_seam.py`
删 AgentChatService/DeepResearchService/SkillMarketplaceService 参数化行、
`test_di_wiring_completeness.py` 清空 SEMANTIC_REQUIRED 与 KNOWN_WIRING_GAPS、
`test_batch6a_seam_completion.py` 删 6a-4 skill_checker 测试与 engines/agent 候选目录。

**配置清理**：`yaml_config/config.py` 删 `SandboxConfigYaml`/`AgentMemoryConfigYaml`/`AgentConfig`
与 `DeepResearchConfig` 系三类及 `ProjectConfig` 对应字段；`loader.py` 删对应加载段；
`default.yaml`/`default.example` 删 `agent:` 段。deploy 脚本、Dockerfile、nginx、compose 经勘探
确认零 agent 专属逻辑，不动。

**批次验证**：conftest 通过（prompt 注册 40 条）、`create_app()` 正常、openapi 基线重生成
（206 → 132 paths，agent 域 44 条端点消失）、架构门禁 280 全绿、全量 pytest 通过、ruff clean。

### 2.2 批次 2：前端剥离（commit `6cec2cd9`）

**前置迁移**：`ApiKeyView` 用的 3 个 API key 接口（`listKeys/createKey/revokeKey`）藏在待删的
`api/agent.ts` 尾部——先迁入 `api/user.ts` 再删文件。

**删除**（76 个文件，+70/−21439 行）：`views/{agent, chat, skill, app}`、
`components/{agent(23 文件 8004 行), workbench, skill, pdf}`、`stores/{agent/, agentGroup, workbench, skill}`、
`api/{agent(迁移后), agentGroup, skill, app}.ts`、`composables/{useTrajectoryRecords, useWorkspaceBinding}`、
`utils/{chatRender, attachmentPreview, memberColor}`、common 下 agent 专属组件与四个零引用死组件。

**改造**：

- `router/index.ts`：删 `/home/workspace` 子树、`/home/apps` 子树、6 个顶层 redirect 桩、
  `WorkspacePassThrough`；`guards.ts` 删 `requiresApp` 分支；`types/index.ts` 删 RouteMeta 声明。
- `layouts/WorkspaceLayout.vue`：从 1404 行重写为 117 行——它是 `/home` 全站唯一布局且深度耦合
  agent（侧栏会话中心三分类、助手抽屉、4 个 manage 弹窗、WorkbenchDrawer、onMounted 无条件拉取
  agent 数据），保留顶栏 + 主内容容器骨架，其余全删。
- `layouts/AppHeader.vue`：导航项删「工作台」「应用」，删折叠按钮联动与死样式。
- `views/HomeView.vue`：重写为知识空间门户——Hero 文案改知识服务定位，主 CTA 指向 `/home/spaces`，
  功能卡只剩「知识空间」，数据条只剩空间数与 Wiki 页数。
- `views/LandingView.vue`：三张产品卡改为「语义检索 / Wiki 沉淀 / 开放接口」。
- `api/types.ts`：按段删除 agent/群聊/会话配置/深度研究/聊天/技能/应用类型段（约 750+ 行）与
  `APP_CODES`，ApiKey 类型段保留。
- `views/user/UserManageView.vue`：删除应用权限弹窗整条链路（下拉项/弹窗/command/逻辑段/import）。

关键的事实基础：**知识空间 UI 对 agent 组件/store/api 的依赖为 0**（双向零交叉，仅 MarkdownRenderer
等公共组件共享），所以前端剥离在类型层完全干净，type-check 一次通过。

**批次验证**：`type-check` / `lint` / 71 个 Vitest 单测 / `build` 全绿。

### 2.3 批次 3：文档收口（commit `533dc66c`）

- **删除**：`docs/agent/group-chat-frontend-design.md`（自标已被取代）、`backend/docs/api/agent_api.md`。
- **归档**（git mv 至 `docs/agent/historical/` 与 `docs/plans/historical/`）：工作台前端架构、
  群聊前后端设计、本地工作区 runner 设计、Plan-and-Execute 流、工具体系 5 份设计稿，
  `backend/docs/agent_framework.md`，`docs/plans/active/` 的 3 份 agent 计划。
- **保留并更新**：`claude-code-mcp-setup.md` 与 `openai-gateway.md`（讲的就是保留的 agent_api 出口）、
  `docs/README.md`（「Agent / Deep Research 子系统」小节重写为「知识服务出口」）、
  `project-structure-navigation.md`、`knowledge-architecture-navigation.md`、根 `AGENTS.md`/`CLAUDE.md`
  与 `frontend/AGENTS.md` 的定位表述。`multi-agent-parallel-development-workflow.md` 保留——
  它讲的是多窗口开发 worktree 规范，与产品 agent 无关。

---

## 三、残留检查与清理（第二阶段）

剥离完成后，派了四路检查 agent 从互补视角扫残留——前三路静态扫描 + 一路运行时动态验证，
然后按结论全量清理。

### 3.1 四路检查的视角与主要发现

1. **后端源码扫描**：P0（import/符号/装配点）全部干净；挖出 8 处死代码——死权限码
   （`skill.review`/`skill.config`/`agent.manage_system` 仍在 `SystemPermission.ALL` 且启动 seeding
   写入 DB）、通知死枚举（`RESUME_COMPLETED`/`RESEARCH_DONE`/`SKILL_REVIEW`）、
   `ensure_fulltext_indexes`（唯一职能是给 skill 表建索引，启动期还在跑）、mem0 extra 孤儿、
   `skill_marketplace` yaml 死段、`shared/message_attachments.py` 孤儿模块、Mem0 专用模型连接
   参数方法、以及 rag 的 QueryRewriter/GradeRetrier 链（原消费方是 agent 检索路径）。
2. **前端源码扫描**：唯一真死链——运营区「点踩/低分回答」条目仍 `router.push('/home/workspace/chat')`
   （点击必 404）；另有 `pdfjs-dist` 孤儿依赖、NavIcon 5 个死图标分支、通知偏好死类型开关、
   角色管理死权限分类、四处失实文案。
3. **配置/部署/文档扫描**：`.env.example`、docker 全套、deploy 脚本、CI 工作流全净；
   openapi 基线 132 paths 改净；发现文档断链 20+ 处（归档移动未同步）、`backend/docs/api/` 还有
   4 份已删功能的 API 文档漏删、README 系列与规则文件的大量产品能力表述残留。
4. **运行时动态验证 + API 契约对账**（静态扫描抓不到的层）：
   - 活路由表 132 条零死域端点；前端 141 个 API 调用点全部指向活端点，零断链；
   - 启动日志干净，WS 全仓只剩通知一条，arq 9 函数 5 cron 零死引用；
   - **数据库死数据实锤**：21 张死表带约 2670 行历史数据；permissions 表 3 个死码还在实跑且
     管理员/编辑者两角色各绑 3 行；7 行死类型通知；admin 偏好订阅 3 个死类型；
   - Redis 1 个持久死键 `skill:llm_review_enabled`；
   - 4 个「孤儿端点」（后端活着但前端再无消费者）：文档审核确认、生命周期动作、复审设置、
     AI 生成测试集。

### 3.2 清理批次（commit `a899f745` / `40e7bd2c` / `def717ba` + 数据脚本）

**后端清理**（`a899f745`，33 文件 +710/−2804）：

- 权限码收敛：`SystemPermission.ALL` 收敛为 `user.manage`/`role.manage`，seeding 元数据同步。
- 通知枚举收敛：删 3 个死类型成员与列 comment。
- **4 个孤儿端点下线**：删 HTTP 路由 + 无消费的服务代码，但保留有活消费者的部分——
  `LifecycleService` 保留（kb-ops 建议处置链路仍自动执行 supersede）、`document_review_service`
  只留模块级函数 `load_review_config`/`compute_next_review_at`（复审 cron 与运营概览仍消费，
  存量复审配置继续生效）、kb-ops 的矛盾检测/归因/周报链路不动。`testset_generation` 服务模块
  整删（唯一入口是下线的端点；quality_baseline 走独立的 standalone_factory，不受影响）。
- **rag 改写器链删除**：`query_rewriter.py`/`grade_retrier.py`/`prompts.py` 与
  `QA_RW_*`/`QA_GRADE_RETRIEVAL`/`EVAL_TESTSET_GENERATION` prompt 键。宿主查询改写走
  search_service 独立实现（两条并行路径之一，见 prompt 注册表架构约定），不受影响。
- 杂项：`ensure_fulltext_indexes`、`message_attachments.py`、Mem0 专用方法、三处失实 docstring、
  pyproject 的 mem0 extra（`uv lock` 重算）。

**前端清理**（`40e7bd2c`）：SpaceOpsGaps 死链条目降级纯展示、通知偏好/标签/图标死类型移除、
RoleManage 死分类移除、NavIcon 死分支删除、`npm rm pdfjs-dist`、ModelConfigView 联网搜索文案等
四处失实表述。

**文档清理**（`def717ba`，含全部断链修复）：根 `AGENTS.md`/`CLAUDE.md` 引擎清单与 shared/document
复用表述、`backend/CLAUDE.md` 整体同步（它与 backend/AGENTS.md 是并行维护的镜像）、
`backend/docs/api/` 4 份漏删文档（deep_research/resume_mining/skill/qa）、README 与 README.en 的
产品叙事重写（工作流句、智能应用节、仓库树、API 表）、ROADMAP/backend-README/frontend-README、
permission-architecture（权限码 5→2、可门禁应用表清空）、notification-architecture（发送方清单）、
single-process-boundary-conventions（删 3 行 agent 状态点）、wiki-architecture（Agent 工具节加
剥离注记）、kb-ops-loop-summary（三段式架构变更注记）、multi-agent 工作流示例域、nginx 注释；
另跑了一个相对链接自愈脚本修复 24 处历史断链（归档移动造成的相对深度错误），终扫确认
**归档目录之外零断链**。

**数据清理**（一次性脚本，不入 git）：

- 先用「保留代码 ORM `Base.metadata` 声明表 ∩ `SHOW TABLES` 实际表」的**差集**精确圈定死表，
  人工核对后 **DROP 21 张**（agent 系 12、skill 系 4、chat_attachments、qa_session_summaries、
  research_sessions、resume_sessions、runner_devices）。运行时检查 agent 给的「25 张死表」清单
  有 4 张误报——`video_narratives` 是保留的视频叙事功能表、`question_answers` 是 knowledge_ops
  活表、`agent_api_keys` 是保留网关的活表——盲目照单执行会删掉活数据。
- `DELETE permissions` 3 行 + `role_permissions` 6 行绑定（顺序：先删绑定再删权限码）；
  `DELETE notifications` 7 行死类型；`notification_preferences` 逐行清死订阅（JSON 列经 `text()`
  查询返回 str 需 `json.loads`）；Redis `DEL skill:llm_review_enabled`。
- MySQL drop 有 FK 依赖序问题（agent_tool_calls → agent_messages），会话级
  `SET FOREIGN_KEY_CHECKS=0` 绕过后恢复。

**工程卫生**：15 个已删模块的目录壳（git rm 只删跟踪文件，`__pycache__` 残骸导致目录未消失，
共 358 个 .pyc + `skill/data/admin_settings.json`）与 `novamind.egg-info` 旧清单全部清除，
避免 IDE 与全文检索误命中。

**清理后验证**：后端全量 2708 passed（4 个 presign 失败为已知的全量偶发干扰，单跑全过）+
架构门禁全绿 + ruff clean；前端 type-check/lint/71 单测/build 全绿；真机重启后端后验证——
登录正常、`/me/permissions` 只返回 `["role.manage","user.manage"]`（死码消失且新 seeding 生效）、
通知偏好只剩 4 个活类型、知识空间列表正常、MCP 建号→kb_search→吊销全链路 200。

---

## 四、过程中的关键教训

1. **模块级 import 的连锁半径要提前算**。`prompt_registration.py` 被 conftest 的 autouse fixture
   依赖——删 feature 前必须先改它，否则全部测试崩。同类：`exceptions.py` 影响 3 个 `create_app`
   测试。装配点的修改与目录删除必须同 commit 原子完成。
2. **门禁白名单对过期条目零容忍**。savepoint gate / cross-feature gate 的白名单文件被删即挂，
   删模块与删白名单条目必须同 commit。
3. **「按段注释到段注释」的文本切分会误吞中间的保留内容**。本系列犯了两次同型错误：
   前端 `types.ts` 按段切分误吞了夹在「聊天相关」段里的 KbOps/KnowledgeGap/ChunkPosition 类型群；
   后端 `document_schema.py` 删到文件尾时误吞了其后的 `DocumentTagsUpdateRequest`/
   `DocumentBatchProcessResponse`。两次都靠 type-check/pytest 抓住、从 git HEAD 按类型边界恢复。
   正确姿势：切分前先列出区间内全部顶层定义核对，切完立即全量编译验证。
4. **自动 agent 的清单不能盲信**。运行时检查 agent 给出的死表清单有 4/25 误报。删除类操作
   必须用确定性方法二次核对（ORM metadata 差集）+ 人工确认，宁可多花一步。
5. **text() 查询 JSON 列返回原始 str**。清理脚本按 list 迭代导致第一次偏好清理静默未生效，
   `json.loads` 后重跑才成功——数据清理后必须回读验证（本例回读抓到了）。
6. **死代码的判定要看「链路」而非「引用计数」**。`LifecycleService` 引用计数低但 kb-ops 建议处置
   在消费 supersede；`load_review_config` 的类被删了函数还活着——逐方法核对消费方再决定删多深，
   避免「删端点顺手删服务」弄断保留功能的自动化链路。

---

## 五、最终形态

### 5.1 产品定位

> **NovaMind = 知识空间独立服务**：一个应用、一个受众叙事、一条价值链——
> 运营人员在知识空间治理知识（解析 → 切分 → 向量化 → 检索 → Wiki → 评测 → 运营闭环），
> 任何 agent 宿主经标准接口消费知识。

登录后首页即知识空间门户（Hero 主 CTA → `/home/spaces`）；侧栏导航只剩「首页 / 知识空间 / 系统」；
旧工作台 URL（`/home/workspace/*` 等）由 catch-all 落 404。

### 5.2 保留的模块与职责

| 层 | 模块 | 职责 |
| --- | --- | --- |
| features | `knowledge_space` | 空间/知识库/文档/成员/Wiki/检索/视频叙事（产品主体） |
| features | `knowledge_ops` | 知识运营：事件账本、失败归因、缺口闭环、建议队列、质量基线、治理视图 |
| features | `user` | 认证、用户/角色、模型配置、搜索配置、API key 管理 UI |
| features | `evaluation` | 测试集、评测任务、导出（被 knowledge_ops 硬依赖） |
| features | `notification` | 站内通知（WS 推送 + 轮询兜底 + 偏好） |
| features | `agent_api` | **知识服务出口**：MCP server（`/mcp`，kb_search）、OpenAI 兼容网关（`/v1/chat/completions`、`/v1/models`）、API key 门禁 |
| engines | `document` / `rag` / `wiki` / `question_generation` / `video_narrative` / `eval` / `search` | 可复用引擎层（零 features/setting 依赖） |
| core / shared / setting | — | 应用工厂、WS（仅通知）、权限门禁（空表）、prompt 注册表（knowledge_space/evaluation 两域 40 模板）、配置 |

### 5.3 对外接口面（openapi 128 paths）

- 知识空间域：空间 5 / 知识库 4 / 文档 29（含分片上传）/ Wiki 16 / 检索 3 / 成员 7 / 统计 3
- 评测 13、知识运营 9、用户 14、角色 4、模型配置 6、搜索配置 4、通知 5、健康检查 5、指标 1
- 对外出口：`/api/v1/agent-api/keys`×2（API key 生命周期）、`/v1/chat/completions` + `/v1/models`
  （OpenAI 兼容网关）、`/mcp`（MCP server，非 openapi 记载）
- WS 仅一条：`/api/v1/notifications/ws`

外部宿主接入方式（详见 `docs/agent/claude-code-mcp-setup.md` 与 `openai-gateway.md`）：
创建 API key（明文仅创建时返回一次）→ MCP 客户端带 `X-API-Key` 连 `/mcp` 使用 `kb_search` 工具
（权限链完整继承 key 归属人的空间成员与文档过滤），或以 OpenAI 协议直连 `/v1`。

### 5.4 规模与质量变化

| 维度 | 转型前 | 转型后 |
| --- | --- | --- |
| 后端测试 | 3705 passed（含 agent 47+26 文件） | 2708 passed + 119 skipped |
| 前端单测 | 71 passed | 71 passed |
| openapi paths | 206 | 128 |
| prompt 模板 | 8 个模块 8 域 | knowledge_space + evaluation 两域 40 条 |
| 权限码 | 5（含 3 个死码） | 2（user.manage / role.manage） |
| 数据库表 | 50 | 29（drop 21 死表，video_narratives 等活表保留） |
| 代码量 | — | 累计删除约 10.5 万行（git deletions：78971 + 21439 + 1821 + 2804 + 前端/文档清理小项） |

依赖面同步收窄：uv.lock 移除 mem0ai 及其传递依赖；前端移除 pdfjs-dist。

### 5.5 本次全部提交（本地 main，未推送）

```
96a0fe76 refactor: 剥离工作台后端——agent/skill/deep_research/app 四模块及引擎、装配点门禁基线同步收敛
6cec2cd9 refactor: 剥离工作台前端——对话/技能/应用视图组件与路由收敛为知识空间门户
533dc66c docs: 剥离工作台文档收口——设计稿归档 historical，导航与规则文件同步知识空间定位
a899f745 chore: 剥离残留清理——死权限码/通知枚举/孤儿端点/rag 改写器链/杂项死代码
40e7bd2c chore: 前端残留清理——运营区死链降级、通知死类型、死图标分支与孤儿依赖
def717ba docs: 剥离残留文档清理——规则文件同步、README 重定位、断链自愈、能力表述收敛
```

---

## 六、遗留与后续方向

1. **MCP 工具面补齐**（下一个独立批次）：出口目前仅 `kb_search` 一个工具，对话答疑只靠检索
   片段不够——LLM 需要读文档原文、翻文档列表、读 Wiki 页确认引用。计划把内置工具能力面映射成
   MCP 工具集（kb_read_document / kb_list_documents / wiki 读页等），并同步更新 skill 分发包。
   这是「知识空间服务化」定位成立的核心能力补全。
2. **复审与生命周期的人工入口**：4 个孤儿端点下线后，复审策略设置与文档生命周期转换失去了
   UI 入口；自动化链路（复审提醒 cron、kb-ops 建议处置 supersede）仍正常消费存量数据。若知识
   空间文档页未来需要「确认复审/设置周期/新版替代」按钮，后端需按现契约补回入口（服务层
   `LifecycleService.supersede` 与 `load_review_config` 公共面都在，回补成本低）。
3. **攒批推送**：本系列 6 个 commit 加此前积累共 40+ 提交在本地 main 未推送，待整体审阅后推送。
4. **环境杂项（非本仓库问题）**：开发机 Redis 与另一项目共库（seckill:* 键约 67 个），建议分实例。
5. **远期**：若产品需要面向 C 端/个人开发者的对话形态，那是新产品的立项问题（独立的宿主/客户端），
   不回填到本仓库——知识空间经 MCP 已是它最标准的消费方式。
