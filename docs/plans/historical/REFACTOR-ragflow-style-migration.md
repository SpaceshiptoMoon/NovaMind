# REFACTOR：NovaMind 迁移 ragflow 务实单体风格（详细版 v2）

- **状态**：✅ 已完成（2026-09-21）——批次 0-6 全部执行并合并 main，R1-R6 已写入两份 CLAUDE.md；
  三门禁（无环 / 禁私有 / 禁 HTTPException）已生效。后续演进见
  [`REFACTOR-ragflow-style-alignment-round2.md`](./REFACTOR-ragflow-style-alignment-round2.md)
  与第三轮仪式清除（commit f49558c..145f1b2）。本文仅作历史工作底稿保留。
- **日期**：2026-09-20
- **基线**：main @ 32c39ff
- **上游参照**：`.tmp/ragflow`（风格样本，机制对照见 §0）
- **前置审计**：《NovaMind 项目问题审计报告》（2026-09-20）
- **v2 变更**：按文件:行号级细化全部批次；修正 v1 四处事实错误——①无 marker 测试文件严格口径 34 个（非 63，63 是"无模块级 pytestmark"宽口径，其中 57 个有函数级标记仍被 CI 收集）；②`docs/transaction-boundary-conventions.md` 不含"单向依赖"字样，无需改写（v1 误列）；③对话压缩收敛方案修正——agent `ContextCompressor` 是 agent 记忆域（MemoryMessage/工具结果修剪），与 qa 会话压缩不是同一域，**不合并**，真正的重复对是 qa_service 内联四策略 vs `shared/utils/text_utils/text_compressor.py`；④search_mode 字面量实测 11 处（非 7）。

---

## 0. 背景与决策

审计结论：端口-适配器骨架质量不低（engines 层零违规、AST 门禁有效），但 features 层横向依赖 80+ 条边失守、port 仪式未推广到全部边界、工程护栏滞后于功能。

**用户决策**：放弃"分层铁律 + 端口注入"路线，整体转向 ragflow 式务实单体——全局中心 + 直接 import + 工厂自注册 + 胖服务类，用"依赖指向公认中心 + import 无环"替代"依赖倒转"。

ragflow 机制对照（已核实）：

| ragflow 机制 | 位置证据 | NovaMind 对应物 |
|---|---|---|
| 全局配置中心，人人可 import | `common/settings.py`、`rag/settings.py` | `setting/yaml_config/loader.py` 的 `get_config()`（已存在） |
| 工厂自注册：类挂 `_FACTORY_NAME`，模块扫描入注册表 | `rag/llm/__init__.py:177-192` | `shared/ai_models/`（批次 2 引入） |
| 跨模块只走对方 service 公共类 | `api/apps/services/dataset_api_service.py:18-20` | features 间直接 import service（批次 3/4） |
| 胖路由直接 import DB 模型 | `api/apps/restful_apis/document_api.py:42` | wiki_routes 直查（合法化，但算法仍须出路由） |
| 有门禁，规则不同 | `lefthook.yml`、`codecov.yml` | 批次 1 用"无环 + 禁私有"门禁替换单向依赖门禁 |

## 1. 目标状态：新规则 R1–R6（迁移完成后写入两份 CLAUDE.md）

- **R1 废止分层铁律，新约束是 import 无环**。`features`/`engines`/`shared`/`setting`/`core` 之间允许任意方向 import（含 engines→features、core→features），机器门禁保证整个 `src/` 模块级 import 图（含函数内懒 import 边）无环。
- **R2 跨 feature import 走公共面**：允许 import 对方 `services/` 公共类、`schemas/`、`models/` 中显式导出的枚举与行级只读访问；**不** import 对方 `repository/` 内部（repository 是 feature 私有实现）、不下划线私有成员（后者机器门禁）。**防环细则：需要对方数据但对方 service 已依赖自己时，import 对方 `models/` 直查，不 import 对方 `services/`**（典型：user ↔ knowledge_space，见任务 4.5）。
- **R3 全局中心清单**（只进不改，热点文件串行编辑）：
  - `setting/`：`get_config()`——engines 自此允许 import setting（ragflow `rag/settings.py` 模式）
  - `shared/prompts/prompt_manager.py`：PromptManager（实测零重依赖）
  - `shared/ai_models/`：模型客户端工厂（批次 2 自注册化，含 `connection_testers/`）
  - `shared/storage/client_factory/`：ES/MinIO/Redis 单例（直呼合法化）
  - `shared/search/external_search_service.py`：web 搜索唯一工厂（批次 2 收敛）
  - `shared/mq/`：arq 任务运行时（TaskTracker 通用部分；域函数批次 6 下沉）
- **R4 引擎不再定义 Protocol 端口**。引擎需要宿主能力时：prompt → 直接收 `PromptManager` 实例；宿主数据 → 调用方取好后以普通参数传值（plain data / 具体类）。引擎 import features 具体类在 R1 下合法（需过无环门禁）。
- **R5 工厂自注册**：模型客户端（llm/embedding/rerank/asr）与 web 搜索源采用 `_FACTORY_NAME` 属性 + 模块扫描注册，消灭 if-else 供应商分支链。
- **R6 与风格无关的硬规则全部保留**：BaseAPIError 体系、`begin_nested()` SAVEPOINT、密钥加密、异步密码哈希、JWT 黑名单、FileValidator 魔数校验、参数化查询、路由手动注册、模块 init 注册、openapi 快照门禁、鉴权覆盖门禁、源码编码门禁。

## 2. 现状资产盘点（迁移要消化的存量）

| 资产 | 规模（实测） | 处置批次 |
|---|---|---|
| feature 适配器 | 6 feature 共 16 文件 / 1636 行（agent 5、deep_research 3、knowledge_space 3、user 3、notification 1、app 1） | 3.3/3.4/3.5/3.6 删除 |
| 端口协议文件 | `engines/ports.py`（PromptProvider/FallbackLLMProvider）、`engines/search_ports.py`（WebSearchPort/WebSearchResult + 引擎默认实现）、`engines/agent/ports.py`（**5 个 Protocol + 8 个 dataclass**）、`engines/deep_research/ports.py`（InternalSearchPort）、`engines/prompt_provider_adapter.py`、`shared/{model_config,notification,registry,search_config,retrieval}_ports.py`、`features/user/ports.py`、`core/auth/ports.py` | 2.3/3.6/3.7 删除或降级为纯数据类型 |
| 其中最大端口：ModelConfigPort | **17 处消费**（qa 2、agent 1、ks 5 service、skill 1、evaluation 1、deep_research 1、engines/agent/subagent 1、user deps 1 等，全表见附录 B） | 3.6 批量改类型注解 |
| 纯透传适配器（删除零成本） | `search_config_port_adapter.py:15`（直接 `return SearchConfigService(db)`）、`registry_ports` 的 HostAgentRegistryPort | 3.6 |
| 守边界 seam 测试 | 10 个（architecture 3 + engines 7，全表见附录 F） | 行为断言保留改写，"零 import"守边断言随 R1 失效删除 |
| AST 单向依赖门禁 | `test_unidirectional_dependency_gate.py` + `test_core_auth_no_feature_imports.py` | 1.2 删除 |
| 铁律文本面 | 2 处 CLAUDE.md 规范段 + 7 处源码注释 + 1 处导航文档（全表见附录 E） | 1.3 |
| `source_registry` import 副作用单例 | `deep_research/adapters/source_registry.py:70,94` | ragflow 风格下合法化保留 |
| `skill/ports.py` 的 ReviewStatus | **不是 Protocol，是 IntEnum**（PENDING/APPROVED/SUSPICIOUS/REJECTED），被 ORM 列 default 引用同一性 | 并入 `skill/models/skill.py`（已 re-export），删 ports.py |

## 3. 批次计划

> 全程 `refactor/ragflow-style` worktree 分支；每任务独立 commit；每批完成跑 `pytest -m unit` + 该批验收项后进下一批。commit message 按项目规范 `refactor(<scope>): 中文动机`。

### 批次 0：护栏先行（1 天）——大动结构前先张测试网

**任务 0.1 补全 unit marker（附录 A 的 34 个文件）**
- 每个文件头部加 `pytestmark = pytest.mark.unit`（`--strict-markers` 已启用，`unit` 已在 pytest.ini 注册，无额外注册工作）。
- 已知特例：`tests/engines/document/deepdoc/` 11 个文件中 `test_deepdoc_integration_light.py` 若确需外部服务，改标 `pytest.mark.integration`；`tests/core/test_endpoint_permissions.py`、`test_require_permission.py` 补 unit 后必须本地跑通（权限测试依赖路由注册，确认无 :8100 依赖）。
- 验收：`pytest -m unit --collect-only -q | tail -1` 从 1096 升至 **≥1600**（1699 − 96 integration）。

**任务 0.2 ruff 规则集进 CI**
- `backend/pyproject.toml` `[tool.ruff.lint]`：`select = ["E", "F", "W", "I", "UP", "B"]`（现配置仅 `line-length=100`/`target-version=py312`）。
- 先跑 `ruff check . --fix`（I/UP 类自动修），剩余手工分两波清；当日清不完则临时降为 `["E", "F", "I", "UP"]` 先上门禁，W/B 第二波补——**门禁当天必须绿**。
- CI `backend-smoke` job 增加步骤：`uvx ruff check .`（在 pytest 前）。
- vendored 豁免：`[tool.ruff.lint.per-file-ignores]` 加 `"src/engines/document/integrations/deepdoc/**"`（上游逐字 vendor 禁改）。

**任务 0.3 CI 消费 uv.lock**
- ci.yml `backend-smoke` 安装步骤替换：`pip install -e ".[test]"` → `astral-sh/setup-uv@v5` + `uv sync --frozen --extra test`（uv.lock 597 包钉版生效）。

**任务 0.4 禁私有访问门禁（为 R2 铺路）**
- 新建 `tests/architecture/test_no_cross_module_private_imports.py`：AST 扫描 `src/`，禁止跨模块 `from X import _name`（同模块内私有使用不拦）。
- 白名单（复用 `test_unidirectional_dependency_gate.py` 的"白名单条目仍有效"自检模式，防过期）：
  1. `features/knowledge_space/services/media_processing.py:622` import `_asr_busy_lock` → 任务 4.4 清
  2. `features/qa/services/ai_chat_service.py:262,289` 调 `qa_service._get_compression_llm_client` → 任务 4.6 清
  3. `features/agent/services/chat_service.py:637,666` 调 `_get_agent_or_fail` → 任务 4.6 清
- 验收：门禁绿且白名单恰好 3 条；`pytest -m unit` 全绿；CI 三个 job 全绿。

**任务 0.5 HTTPException 门禁**
- 新建 `tests/architecture/test_no_direct_httpexception.py`：扫描 `src/` 禁 `raise HTTPException`，per-file-ignores 豁免 `engines/document/integrations/deepdoc/server/**`（vendored 独立子服务，15 处）。
- 白名单：`core/auth/dependencies.py` 6 处 → 任务 4.9 收敛后清。

### 批次 1：规则换轨（0.5 天）

**任务 1.1 无环门禁上线**
- 新建 `tests/architecture/test_import_acyclic_gate.py`：AST 收集 `src/` 全部 import 边（模块级 + 函数级懒 import 均计），Tarjan 强连通分量检测，断言零环。
- **先跑后改**：若现存环（候选风险：`agent/services/chat_service.py:43` 顶层 import qa 的 `ChatAttachmentRepository` 与 `qa/tasks/attachment_cleanup.py:40-42` 懒 import agent 的 `AgentMessage`——经分析是两条不相交边，模块粒度大概率无环，但以门禁实测为准），发现环先解环（把懒 import 改为延迟到函数内局部、或引入数据契约模块，与任务 4.3 合并处理），解环工作量不可预估则回退本计划重新评估。

**任务 1.2 删除旧门禁**
- 删 `tests/architecture/test_unidirectional_dependency_gate.py`、`tests/architecture/test_core_auth_no_feature_imports.py`（git 可回溯）。

**任务 1.3 规范文本换轨**（单点文件，单人单批）
- 根 `CLAUDE.md:185` 附近的"单向依赖铁律"bullet → 替换为 §1 的 R1–R6。
- `backend/CLAUDE.md:108-114` "单向依赖铁律（硬规则）"整节 → 同上替换；端口归属判据段删除。
- `docs/project-structure-navigation.md:35` "`features → engines → shared 单向依赖`" → 改为"无环 + 中心清单"表述。
- 源码注释 7 处（附录 E C2 清单）：`core/auth/__init__.py:4`、`core/auth/ports.py:5`、`shared/storage/attachment_presign.py:5`、`features/agent/adapters/attachment_read_adapter.py:6`（该文件批次 3.5 整删，可跳过）、`engines/agent/agent_engine.py:109`、`tests/architecture/test_unidirectional_dependency_gate.py`（随删）、`tests/engines/test_web_search_port_builder.py:8` → 改为无环表述。
- `docs/plans/active/` 另两个 active 计划（agent-capability-enhancement-plan.md:262,275、agent-capability-pluggable-plan.md:106）中"跑单向依赖门禁"验收行加过时标注。历史文档（superpowers/、docs/plans/historical）不改。

**任务 1.4 tests/README.md** 架构测试说明同步（删两个门禁、加三个新门禁）。
- 验收：全仓 grep "单向依赖" 仅剩 docs/plans 历史文档与迁移计划自身；无环门禁绿；CI 绿。

### 批次 2：中心建设（2 天）

**任务 2.1 web 搜索唯一工厂**（消"4 份构造逻辑"）
- 目标：`shared/search/external_search_service.py` 成为唯一构造点，语义保持"用户配置的 provider（SearchConfigService）优先 → YAML 默认（Tavily）→ DuckDuckGo 兜底"。
- 合并来源（四份逐字级重复，全量消化）：
  1. `engines/search_ports.py:83-154` `build_web_search_port_from_provider`（引擎默认实现）
  2. `features/deep_research/adapters/web_search_port_adapter.py:25-113`（HostWebSearchPort + build_web_search_port + build_web_search_port_for_provider）
  3. `features/qa/services/ai_chat_service.py:707-808`（`_resolve_web_search_port` + `_build_yaml_fallback_port`，含 `_resolve_web_search_port` 的择优逻辑）
  4. `features/agent/adapters/web_search_adapter.py:17-59`（`resolve_web_search_port`，现为 deep_research 版的 re-export）
- 调用方收敛：qa `ai_chat_service`、agent deps `dependencies.py:126-128`、deep_research service、app `resume_pipeline_service.py:60` 全部改调共享工厂。
- R5 化：tavily/serpapi/duckduckgo 三 provider 类挂注册属性，工厂按 provider 名查表。
- `WebSearchPort` Protocol 定义暂留（批次 3.7 统一删），先迁实现。
- 测试：`tests/engines/test_web_search_port_builder.py` 迁至 `tests/shared/` 改写；`tests/features/qa/test_ai_chat_web_search.py` 行为回归。

**任务 2.2 模型工厂自注册 + 连通测试下沉**（消"ASR 三协议内嵌 user service"）
- `shared/ai_models/__init__.py` 建 `_FACTORY_NAME` 注册表（照抄 ragflow `rag/llm/__init__.py:177-192` 的模块扫描模式）。
- `features/user/services/model_config_service.py:755-835` 的三份 ASR 协议实现（`_test_asr_local:755`、`_test_asr_openai:791`、`_test_asr_dashscope:835`，约 140 行）+ LLM/embedding/rerank 测试 → 拆到 `shared/ai_models/connection_testers/{llm,embedding,rerank,asr}.py`；service 只留门面（`:612-887` 对应调用段）。
- 注意保留 `:815` OpenAI 默认 URL、`:855` 样例音频 URL 的现有语义，但 URL 常量移入 `shared/ai_models/` 常量区（消业务层硬编码）。

**任务 2.3 PromptManager 直用**
- 删 `engines/prompt_provider_adapter.py`（HostPromptProvider 是 PromptManager 的纯委托）。
- 改 6 个构造点：`qa/ai_chat_service.py:118`（service 内自建）、`deep_research_service.py:384`（自建）、`agent/api/dependencies.py:123`、`skill/api/dependencies.py:114`、`app/services/resume_pipeline_service.py:59`、`engines` 内其它 `as_prompt_provider()` 引用 → 全部直接 `PromptManager()`。
- `engines/ports.py` 的 `PromptProvider` Protocol 定义暂留（引擎签名批次 3 改），本任务只删适配器。
- 验收：`grep -r "as_prompt_provider\|HostPromptProvider" src/` 为零；相关单测绿。

### 批次 3：引擎与端口去 Protocol 化（3–4 天，6 个子批）

> 通用改法：引擎构造函数/方法参数的类型注解从 Protocol 改为具体类（`PromptProvider`→`PromptManager`；`FallbackLLMProvider`→`ModelConfigService`；`WebSearchPort`→共享工厂返回的具体 provider 或保留 duck-typed 注释）；协议文件最后统一删（3.7）。**参数注入的管道本身保留**——构造函数传参是数据耦合，不是要消灭的对象；消灭的只是 Protocol 间接层。

**任务 3.1 eval 引擎**（最小，先固化改法）
- `eval/retrieval_evaluator.py:10,22`、`eval/generation_evaluator.py:10,24`、`eval/claim_decomposer.py:10,16`：PromptProvider→PromptManager。
- `tests/engines/eval/test_batch5_evaluation_seam.py`：删协议存在性断言，留行为断言。

**任务 3.2 rag 引擎**
- `rag/grade_retrier.py:11,30` 同上；`rag/__init__.py:4` 迁移注释清理。
- `tests/engines/rag/test_grade_retrier_seam.py` 同上。

**任务 3.3 resume 引擎**
- `resume/resume_parser.py:13,26`：PromptProvider→PromptManager。
- `resume/resume_probing.py:12,42,45`：PromptProvider→PromptManager；**FallbackLLMProvider→直接收 `ModelConfigService`**（R1 下 engines→features 合法；调用方 `app/services/resume_pipeline_service.py:59-62` 的 `as_fallback_llm_provider(bg_mcs)` 适配器删除，直传 mcs；若适配器含 session 生命周期逻辑，随迁进 resume_pipeline_service）。
- `resume/resume_analyzer.py:11-12,27,29`：PromptProvider→PromptManager；WebSearchPort→共享工厂返回类型。
- `features/app/adapters/host_fallback_llm_provider.py` 整删；`tests/engines/resume/test_resume_engine_seam.py` 改写。

**任务 3.4 deep_research 引擎**
- `engine.py:26` import 及 **8 个方法参数位**（L352,368,440,486,532,699,735,777）：PromptProvider→PromptManager。
- `deep_research_service.py:384` 自建 provider 改 PromptManager；`:41,368,388-411` 的 `HostRetrievalPort` 延迟构造删除，直接持有/构造 `SearchService`。
- `engines/deep_research/ports.py` 的 InternalSearchPort：`adapters/internal_search_port_adapter.py:33-138` 的 HostInternalSearchPort 改为直接调 SearchService 的普通宿主类（去 Protocol 继承），`:20-29` 的 ks import 保留（R2 合法）。
- `deep_research/adapters/web_search_port_adapter.py` 剩余部分已随 2.1 迁走，本任务整删文件。
- 测试：`test_deep_research_engine_{seam,loop,plan}.py` 行为断言保留。

**任务 3.5 agent 引擎**（最大）
- `engines/agent/ports.py`：删 5 个 Protocol（KnowledgeSearchPort L70-117、AttachmentReadPort L137-149、LongTermMemoryStorePort L185-258、ContextSummaryStorePort L262-286、MemorySearchPort L293-335）；**保留 8 个 dataclass**（SpaceInfo/KbInfo/KnowledgeSearchItem/DocumentInfo/DocumentListResult/AttachmentTextChunk/ContextSummaryEntry/LongTermMemoryEntry）——文件降级为纯数据类型载体（可顺手改名 `types.py`，非必须）。
- `features/agent/adapters/` 5 个文件（knowledge_search_adapter 243 行、memory_store_adapter、attachment_read_adapter、agent_registry_adapter、web_search_adapter）：去 Protocol 继承、去 `as_*_port` 工厂名，改名为普通宿主助手类（如 `KnowledgeSearchFacade`），**代码逻辑原样保留**——它们是真正的宿主侧查询/权限逻辑，不是仪式。
- `memory/long_term.py:12,38`、`memory/memory_manager.py:14-19,52`：类型注解改具体类。
- `subagent/runner.py:19`：ModelConfigPort→ModelConfigService（R1 合法；无环门禁验证 features/user 无回边）。
- **ToolContext 保留为运行时上下文总线**（ADR-6）：14 键机制不动（附录 D 处置表）——这是 ragflow 的 context 传递模式，不是端口仪式；值从"协议实现对象"换成具体类对象，键名不变。
- `agent/api/dependencies.py:20-27` import 简化；`AgentChatService` 14 参数签名结构不变。
- 测试：`test_agent_engine_ports_seam.py` 改写。

**任务 3.6 shared 与 core 端口清理**（features 侧消费面，17+7+…处）
- `shared/model_config_ports.py` 删除：17 处消费点类型注改 `ModelConfigService`（全表附录 B）；`ModelCredentials` dataclass 若被引用则迁 `features/user/schemas/`。
- `shared/notification_ports.py` 删除：`as_notification_port(db|None)` 7 处调用（skill deps:123、deep_research deps:26、app resume_tasks:33、user_routes:587、ks wiki_tasks:339,352、ks document_tasks:60,74、ks member_routes:39,54）→ 直接构造 NotificationService 或在 `features/notification/services/` 提供 `build_notification_service(db)` 简单工厂；`features/notification/adapters/notification_port_adapter.py` 整删。
- `shared/registry_ports.py` 删除：`AgentSummary` dataclass 迁 `features/agent/schemas/`；skill deps:120 直构。
- `shared/search_config_ports.py` 删除：`SearchConfigService` 直用（qa deps:19,87、agent deps:126-127、qa ai_chat_service:29,91,749-772）。
- `shared/retrieval_port.py` 删除：`as_retrieval_port` 薄包装（`knowledge_space/adapters/retrieval_adapter.py`）删；消费方（qa deps:15,85、evaluation deps:15,28,33,36、evaluation_service:39,72,75,648、deep_research_service:41,368,388-411、internal_search_port_adapter:30,44,142）直收 `SearchService`。
- `features/user/ports.py`：KnowledgeSpaceInfoPort 部分 → 任务 4.5 处理（有防环设计）；先留。
- `features/skill/ports.py`：ReviewStatus 枚举并入 `skill/models/skill.py`（已 re-export，改 import 源），删 ports.py。
- `core/auth/ports.py` UserStatusResolver + `user/adapters/auth_user_resolver_adapter.py`：core/auth dependencies 直接 import `features/user/repository` 查用户状态，删协议与适配器（user/api/startup.py:290-296 的 dependency_overrides 注册随之删除）。
- `features/user/adapters/search_config_port_adapter.py`、`knowledge_space_info_adapter.py`：前者整删（纯透传），后者随 4.5 改写。

**任务 3.7 端口文件最终删除**
- 删 `engines/ports.py`、`engines/search_ports.py`（协议部分；2.1 已迁实现）、`engines/agent/ports.py` 协议（若 3.5 未删）。
- 全仓验收：`grep -rn "class.*Protocol" src/engines/ src/shared/` 为零（vendored 豁免）；`find src/features -path "*adapters*" -name "*.py"` 仅剩改名后的宿主助手类（agent）或清空；`pytest -m unit` 全绿。

### 批次 4：feature 横向收编与审计硬伤修复（4–5 天）

**任务 4.1 wiki service 提取**（wiki_routes 766 行 → 薄路由；处置表附录 C）
- 新建 `knowledge_space/services/wiki_page_service.py`：承接 create_page（L278）、update_page（L325，乐观锁）、delete_page（L370，含 `_finalize_links` 死链清理 L391-407）、revert_page（L476）、rebuild_wiki（L507，内联 ORM select L532-537 下沉为 DocumentRepository 方法）、create_issue（L702，issue 类型白名单）、update_issue_status（L739，状态机 transition map L753）。
- 新建 `wiki_graph_service.py`：get_graph 的 ego BFS（L585-599）与连通度排序（L601-607）、get_stats（L234）。
- **9 处 handler 内 `db.commit()`（L321,366,387,499,548,681,735,764 + rollback L364）全部随迁进 service，写路径按事务边界规范用 `begin_nested()`**。
- 薄路由保留：参数解析 + Depends 鉴权 + 调 service。`_get_kb_or_404`（L76）换成复用 `validate_kb_access` 依赖。
- 安全网：wiki 已有 37 个测试文件；先跑基线全绿，逐 handler 迁移（每 3–5 个一轮）；`test_openapi_contract_snapshot.py` 应保持绿（契约不变）。

**任务 4.2 wiki_tools 权限收编**（消"两套平行权限实现"）
- `agent/tool/builtins/wiki_tools.py:250-285` 的 `_check_kb_access` + `_is_admin` 删除；knowledge_space 提供服务级可调用（新建 `knowledge_space/services/access_service.py` 包装现 `SpaceAccessChecker` + dependencies 里的空间/成员/管理员判定逻辑，Depends 链与 wiki_tools 共用同一实现）。
- wiki_tools 8 个工具改为调 access_service + 4.1 的 wiki_page_service/wiki_graph_service；`_rename_page` 的三步级联（L543-576）下沉 service；工具内 5 处 `db.commit()`（L408,451,499,576,649）随迁。
- 验收：`grep -n "KnowledgeBaseRepository\|MemberRepository\|WikiPageRepository" features/agent/tool/builtins/wiki_tools.py` 为零；agent wiki 工具测试 + wiki 全链路测试绿。

**任务 4.3 附件契约常量化**（消跨 feature 隐式 JSON 契约）
- 新建 `shared/message_attachments.py`：`ATTACHMENT_EXTRA_KEY = "attachments"`、`read_attachment_ids(extra: dict) -> list[int]`、`write_attachment_ids(extra, ids)`。
- 写方（agent chat_service 写 `AgentMessage.extra`、qa 写 `QuestionAnswer.extra`）与读方（`qa/tasks/attachment_cleanup.py:5-6,56-62` 解析两方 extra）全部改走契约模块。
- 顺带消掉 1.1 发现的潜在环边（attachment_cleanup 懒 import agent.models 保留——models import 不成环，但解析逻辑改用共享函数）。

**任务 4.4 ASR 忙锁公开 API 化**
- `engines/document/media/audio/`：`_asr_busy_lock`（audio_utils.py:127）不再经 `__init__.py:4` 导出；新增公开 API `is_asr_busy()`（:136 已有 `asr_is_busy` 类函数则复用）+ `force_release_asr_slot()`（或 context manager）。
- `media_processing.py:622-624` 改调公开 API；**清 0.4 白名单第 1 条**。

**任务 4.5 user→knowledge_space 嵌入信息查询（防环设计）**
- 现状：`model_config_service.py:33,112,981` 经 `KnowledgeSpaceInfoPort`（user/ports.py）+ `knowledge_space_info_adapter.py:18-37`（直查 KnowledgeSpace ORM 并掏 `config["embedding"]["model"]`）。
- 改法：knowledge_space 侧在 `KnowledgeBaseRepository` 加公共方法 `find_spaces_using_embedding(model_name) -> list[SpaceEmbeddingUsage]`（内部解析 config，含 :27-36 现有逻辑）；user service **import ks 的 repository 与 models，不 import ks 的 services**（ks services → user services 已有边 document_pipeline:45→ModelConfigService，import services 会成环；R2 防环细则）。
- `features/user/ports.py` 与 `knowledge_space_info_adapter.py` 整删；无环门禁验证。
- 同模式修正 `SpaceEmbeddingUsage` dataclass 归属（迁 ks schemas）。

**任务 4.6 私有方法穿透转公共**
- `qa_service._get_compression_llm_client` → 公共 `get_compression_llm_client`（ai_chat_service:262,289 调用点改）。
- `agent_service._get_agent_or_fail` → 公共 `get_agent_or_fail`（agent chat_service:637,666 改）。
- **清 0.4 白名单第 2、3 条**。

**任务 4.7 audio_utils 环境变量改配置中心**
- `audio_utils.py:542,547,629` 的 `OPENAI_API_KEY/OPENAI_BASE_URL/DASHSCOPE_API_KEY` 直读 → `get_config()`（R3 下 engines 可读配置中心）；`:191` 的 `NOVAMIND_LOCAL_WHISPER_MODEL_DIR` 同改。

**任务 4.8 search_mode 字面量收敛（11 处，附录 G 清单）**
- 唯一来源：`knowledge_space/schemas/search_schema.py:12` 的 `SearchMode` 枚举；11 处字面量（`"content_hybrid"` 默认值×7 + `content_modes` 列表 + deep_research schema 的 `Literal` 集 + evaluation schema 默认 + ks API 文档字典）全部改 import 枚举。
- `ai_chat_service.py:55` 的 `_GRADE_RETRY_FALLBACK_MODES` 序列改用枚举成员。

**任务 4.9 core/auth HTTPException 收敛**
- `core/auth/dependencies.py` 6 处 `raise HTTPException`（401/403 认证链）→ 定义 `core/auth/exceptions.py` 的 BaseAPIError 子类（如 `AuthenticationError`/`AuthorizationError`）并注册 handler；**清 0.5 白名单**。
- 验收：批次 0 三个白名单全部清空；`grep -rn "raise HTTPException" src/` 仅剩 deepdoc vendored 15 处。

### 批次 5：重复实现收敛（1.5 天）

**任务 5.1 会话压缩收敛（qa 域）**
- 真正的重复对：`qa_service.py:798-991` 内联四策略（`_compress_with_summary:798`/`_compress_with_sliding_window:908`/`_compress_with_keep_recent:941`/`_compress_with_truncate:959`）vs `shared/utils/text_utils/text_compressor.py`（TextCompressor 类 + CompressionStrategy 枚举，160 行）。
- 步骤：先 grep text_compressor 的实际消费者；**若 0 消费者**（大概率，审计未发现消费点）→ 把 qa 内联四策略提取为 `features/qa/services/session_compressor.py` 作为唯一实现，删 shared 版；若有消费者 → 消费者改调 qa 版（qa 域组件，shared 不留业务组件）。
- **agent `ContextCompressor`（engines/agent/memory/context_compressor.py，794 行）不参与合并**——它是 agent 记忆域（MemoryMessage、工具结果修剪、summarize/prune），与 qa 会话压缩不同域（v1 计划此处判断有误，v2 修正）。
- 回归：qa 会话压缩行为测试。

**任务 5.2 查询改写收敛（迁 engines/rag）**
- 重复对：`qa/services/query_rewriter.py`（4 策略）vs `knowledge_space/services/search_service.py:282 _rewrite_query`（hyde+sub_query）；`shared/prompts/templates.py:44` 注释自认两条独立路径。
- 归属决策：查询改写是检索域逻辑 → **整体迁 `engines/rag/query_rewriter.py`**（engines 可 import PromptManager，R1/R3 合法）；qa 与 ks 两侧调用点改引擎版；`templates.py:44` 注释同步。
- 防环注意：ks.search_service → engines/rag.query_rewriter → shared.prompts，无环。

**任务 5.3 双份小助手收敛**
- `_begin_step`：`document_pipeline.py:124` 与 `media_processing.py:71` 逐字重复 → 提取 `knowledge_space/services/pipeline_steps.py`。
- `_sanitize`：删 `ai_chat_service.py:897` 版，改用 `shared/prompts/sanitize.py`（其 docstring :15 自述"保持一致便于共用"）。
- `extract_key_sources`/`format_search_context`：删 `deep_research_service.py:1395,1399` 版，改调 `engines/deep_research/engine.py:113,151`。
- 验收：每项 grep 全仓唯一实现。

### 批次 6：死代码与遗留开关清理（1 天）

**任务 6.1** 删 `search_service.py` 的 `_search_legacy`（:704-1080，377 行）+ 开关（:437-438）+ docstring（:711）。
**任务 6.2** 删 `NOVAMIND_LEGACY_MANIFEST` 双路径：`router_manager.py:18,40,54`（legacy 硬编码注册方法整段）+ `startup_manager.py:29-31,363-366`（legacy 模型导入分支）。
**任务 6.3** 删 `shared/utils/ansi_strip.py`（0 消费者）。
**任务 6.4 task_tracker 域函数下沉（含 resume 域）**
- `shared/mq/task_tracker.py` 拆三份：通用 `TaskTracker` 类（L18-88）留 shared；**文档域函数**（`bind_job_to_document:90`、`get_job_id_for_document:94`、`unbind_job:98`、`get_active_document_count:102`、`is_document_actively_processing:106`、`purge_document_jobs:138`、`mark_document_cancelled:217`、`is_document_cancelled:221`、`clear_cancel_flag:225`）→ `features/knowledge_space/services/document_task_tracking.py`；**resume 域函数**（`bind_job_to_resume:229` 至 `clear_resume_cancel_flag:249` 共 6 个）→ `features/app/tasks/`（resume 域归 app feature）。
- 6 个消费文件改 import：`app/api/routes.py`、`app/services/resume_pipeline_service.py`、`app/tasks/resume_tasks.py`、`ks/services/document_pipeline.py`、`ks/services/document_task_service.py`、`ks/tasks/document_tasks.py`。
- `test_zombie_job_purge.py` 随迁路径并保持绿。
**任务 6.5** `core/compat/starlette_multipart_patch.py`：确认当前 starlette 版本已修复对应 bug 则删，否则留并注明触发条件。
**任务 6.6 归位小件**
- `minio_client.py:970` 的 `IMAGE_FILE_TYPES` → 新建 `shared/document/file_types.py`（消费方 qa ai_chat_service:32、document_file_types.py:11 改源）。
- `shared/utils/heartbeat.py` → `features/qa/services/`（唯一消费者是 qa，且依赖 ai_models.StreamChunk，名实归位）。
- 验收：`grep -rn "NOVAMIND_LEGACY" src/` 为零；`grep -rn "bind_job_to_document" src/shared/` 为零。

## 4. 并行轨道（风格无关，不因迁移暂停，独立计划推进）

1. **DB 迁移方案重建**（审计 P0）：引入 Alembic 或最小化改造 `schema_migrations.py`（迁移失败**阻断启动**、支持数据回填）——建议在批次 1 之后立即启动，与批次 2-6 并行（不同 worktree）。
2. **可观测性**：`/metrics` 端点（prometheus）、文件日志改 JSON Renderer、arq 死信队列与积压监控。
3. **coverage 接入**：pytest-cov 配置 + CI 报告（与 0.1 衔接）。
4. **engines 测试补课**：splitters（recursive/semantic/fixed）与 `rag/retrieval_engine.py`（662 行）回归测试——迁移后引擎吃具体类/plain 参数，fake 注入更简单，测试更好写。
5. **巨石拆分顺延项**：`ai_chat_service.py`（1593 行）、`document_pipeline.py`（1578 行）、`model_config_service.py`（批次 2 后剩 ~860 行）——批次 5 消重后重估，单独出计划。

## 5. 决策记录（ADR）

- **ADR-1 引擎"零依赖单测"弱化**：引擎将 import PromptManager/ModelConfigService 等。缓解：引擎 API 仍以参数传值为主，测试可 monkeypatch 具体类。
- **ADR-2 多 agent 冲突面增大**：中心文件成热点。缓解：单点文件串行工作流不变（worktree 划分 §9）。
- **ADR-3 标记耦合（config dict 穿透）接受**：ragflow 常态；dict 键契约在消费点注释，不做全链路类型化。
- **ADR-4 全局单例接受并规范化**：ClientFactory/PromptManager/ws_manager 保留；ws_manager 多 worker 失效记录为已知限制（触发条件：部署改多 worker 时引入 Redis pub/sub）。
- **ADR-5 feature 边界由机器门禁降级为"无环 + 禁私有 + service/models-only 约定"**：无环门禁防最坏情况。
- **ADR-6 ToolContext 保留为运行时上下文总线**（v2 新增）：14 键机制是 ragflow 式 context 传递，非端口仪式；Protocol 注解死、键与机制留、值换具体类。`db_session`/`session_id` 两键引擎层零消费（附录 D），暂留（宿主工具在用），不扩新键。
- **ADR-7 适配器"降级"而非"全删"**（v2 新增）：agent 5 个适配器含真实宿主逻辑（权限、查询、记忆存取），改名为宿主助手类保留代码；纯透传适配器（search_config、retrieval、registry）才整删。
- **ADR-8 skill 双配置源（admin_settings.json + YAML）不在本迁移范围**：涉及存量数据兼容，另行决策。

## 6. 风险与回滚

- 每任务独立 commit，出问题 `git revert` 单任务；批间无交叉依赖（3.1-3.5 各引擎子批独立）。
- **不留双轨**：每批完成一类切换即删旧路径——`NOVAMIND_LEGACY_*` 377 行死路径是双轨思维的产物，不重蹈。
- **最大风险**：批次 1 无环门禁上线即红（存在未探明环）→ 解环优先，工作量不可预估则回退计划重评估。批次 4.5 的 user↔ks 防环设计（import models/repo 不 import services）是已知最险点，已给规避方案。
- **次风险**：4.1 wiki 提取行为面大 → 37 个 wiki 测试先跑基线，逐 handler 迁移每 3-5 个一轮；openapi 快照门禁兜底契约不变。
- **ruff 风险**：规则集一次开太宽导致当日无法全绿 → 0.2 预案分两波（先 E,F,I,UP 后 W,B）。

## 7. 审计问题 → 任务映射表

| 审计问题 | 任务 |
|---|---|
| 内容耦合：`_asr_busy_lock` 私有锁 | 0.4 门禁 / 4.4 清零 |
| 内容耦合：qa↔agent extra JSON 契约 | 4.3 |
| 内容耦合：user 掏 ks config JSON | 4.5 |
| 内容耦合：跨 service 私有方法 ×3 | 0.4 门禁 / 4.6 清零 |
| deep_research 跨 feature ORM join（research_repository:123） | R2 合法化（models import 允许），加注释声明 |
| 公共耦合：全局单例 / source_registry 副作用 | 接受（ADR-4）/ 合法化保留 |
| 控制耦合：search_mode 字面量 ×11 | 4.8 |
| 控制耦合：strategy 字符串分支族 | 接受（ADR-3 同精神） |
| 控制耦合：NOVAMIND_LEGACY 双路径 ×6 处 | 6.1 / 6.2 |
| 标记耦合：config dict 穿透 / ToolContext 大杂烩 | 接受（ADR-3）/ 保留总线（ADR-6） |
| 外部耦合：audio_utils 直读 env | 4.7 |
| 外部耦合：skill 双配置源 | 范围外（ADR-8） |
| feature↔feature 80+ 边无门禁 | 1.1 无环门禁 + R2 约定 |
| core→features import（exceptions:13-33 等） | R1 合法化 |
| agent→ks wiki_tools 重写权限 + 6 repository | 4.2 |
| wiki_routes 23 handler 绕 service + 9 commit + BFS | 4.1 |
| 偶然内聚：task_tracker 文档域（+resume 域）函数 | 6.4 |
| IMAGE_FILE_TYPES 归属 / ansi_strip 死码 | 6.6 / 6.3 |
| 重复：压缩 / web 搜索构造 / 改写 / 双份助手 | 5.1 / 2.1 / 5.2 / 5.3 |
| 名实不符：heartbeat / text_compressor | 6.6 / 5.1 |
| CI 只跑 65%（34 文件无 marker） | 0.1 |
| ruff 无规则集 / 无 lint 门禁 / CI 不吃 lock | 0.2 / 0.3 |
| HTTPException 21 处无门禁 | 0.5 门禁 / 4.9 收敛（core/auth 6 处，deepdoc 15 处豁免） |
| DB 迁移 / metrics / engines 测试欠账 / 巨石拆分 | 并行轨道 §4 |
| 端口/适配器 1636 行仪式代码 | 2.3 / 3.x 全部 |

## 8. 工作量汇总

| 批次 | 内容 | 估时 |
|---|---|---|
| 0 | 护栏（marker/ruff/lock/双门禁） | 1 天 |
| 1 | 规则换轨（无环门禁/删旧门禁/文本） | 0.5 天 |
| 2 | 中心建设（搜索工厂/自注册/PromptManager） | 2 天 |
| 3 | 引擎与端口去 Protocol（6 子批） | 3–4 天 |
| 4 | feature 收编与硬伤修复（9 任务） | 4–5 天 |
| 5 | 重复收敛 | 1.5 天 |
| 6 | 死码清理 | 1 天 |
| **合计** | | **约 13–15 个工作日**（并行轨道另计） |

## 9. 多 agent worktree 划分

- 主目录 = trunk 集成位（只做合并与测试）。
- `../intelligent-ragflow-batch0`：批次 0（独立性强，可与计划确认并行开工）。
- `../intelligent-ragflow-engine`：批次 3 引擎子批（3.1-3.5 可再按引擎拆 agent）。
- `../intelligent-ragflow-wiki`：批次 4.1/4.2（最大单块）。
- 单点文件（两份 CLAUDE.md、`external_search_service.py`、`shared/message_attachments.py`、`router_manager.py`、`startup_manager.py`）：批次 1/2/6 期间单一 agent 持有编辑权。

---

## 附录 A：34 个无 marker 测试文件全清单（任务 0.1）

architecture（3）：test_batch6a_seam_completion / test_knowledge_reorg_compat / test_openapi_response_name_determinism
core（4）：test_config_loader_dotenv / test_database_session_factory_no_deadlock / test_endpoint_permissions / test_require_permission
engines/agent（2）：test_agent_engine_ports_seam / test_context_compressor_summary_fixes
engines/document/deepdoc（11）：test_deepdoc_cli / test_deepdoc_entrypoint / test_deepdoc_imports / test_deepdoc_installed_cli / test_deepdoc_integration_light（若需外部服务改标 integration）/ test_deepdoc_packaging / test_deepdoc_parser_alignment_fixes / test_deepdoc_reading_order / test_deepdoc_recognizer_robustness / test_deepdoc_serve_smoke / test_deepdoc_upstream_mapping / test_page_filter_dirty_pattern（此文件在 deepdoc 目录共 12，以实测为准）
engines/document/media（1）：test_media_utils
engines/rag（1）：test_retrieval_engine_seam
features/knowledge_space（8）：test_document_enqueue_batch_atomic / test_document_filename_search / test_document_ownership_guard / test_document_retry_reuses_pipeline_config / test_document_task_batch_repository / test_execute_pipeline_video_branch / test_parsed_text_storage / test_zombie_job_purge
features/qa（2）：test_attachment_cleanup / test_search_cache_key_and_sanitize
shared（1）：test_lru_cache_pattern_delete

> 补 marker 前逐文件确认无 :8100/外部依赖；integration 的 8 个文件（tests/integration/）维持现状。

## 附录 B：端口消费总表（任务 3.6 用）

| 端口 | 定义 | 实现（适配器） | 消费点（改直用后） |
|---|---|---|---|
| ModelConfigPort | shared/model_config_ports.py:23 | ModelConfigService（结构化满足） | qa_service:9,43；ai_chat_service:28,86；agent chat_service:16,57；user deps:6,33；ks search_service:12,77；ks document_pipeline:45,146,706,1062,1320,1346,1385,1410,1507；ks question_generation:18,64；ks space_service:30；ks kb_service:31；ks media_processing:16；skill marketplace:11,53；evaluation_service:73；deep_research_service:10,358；engines/agent/subagent/runner:19 |
| NotificationPort | shared/notification_ports.py:14 | HostNotificationPort（notification/adapters） | skill deps:19,123；deep_research deps:10,26；app resume_tasks:16,33；user_routes:587；ks wiki_tasks:339,352；ks document_tasks:60,74；ks member_routes:39,54 |
| AgentRegistryPort | shared/registry_ports.py:20 | HostAgentRegistryPort（agent/adapters/agent_registry_adapter:10-27，纯透传） | skill deps:18,120；skill marketplace:39,54,262,322 |
| SearchConfigPort | shared/search_config_ports.py:30 | SearchConfigService（纯透传 via user/adapters/search_config_port_adapter:13） | qa ai_chat_service:29,91,749-772；qa deps:19,87；agent web_search_adapter:17,22-59；agent deps:126-127 |
| RetrievalPort | shared/retrieval_port.py:10 | HostRetrievalPort（ks/adapters/retrieval_adapter:11-34，薄包装） | qa deps:15,85；evaluation deps:15,28,33,36；evaluation_service:39,72,75,648；deep_research_service:41,368,388-411；internal_search_port_adapter:30,44,142；engines/rag/__init__:4（注释） |
| KnowledgeSpaceInfoPort | features/user/ports.py:21 | HostKnowledgeSpaceInfoPort（user/adapters/knowledge_space_info_adapter:18-37） | model_config_service:33,112,981（→ 任务 4.5 改造） |
| UserStatusResolver | core/auth/ports.py | UserStatusResolverAdapter（user/adapters/auth_user_resolver_adapter:25） | user/api/startup:290-296 注册（→ 任务 3.6 直连） |
| PromptProvider | engines/ports.py:15 | HostPromptProvider（engines/prompt_provider_adapter:21，纯委托） | 2.3 删适配器；引擎侧类型注解批次 3 改 |
| FallbackLLMProvider | engines/ports.py:36 | HostFallbackLLMProvider（app/adapters:12-33） | resume_probing:12,42,45（→ 3.3 直传 mcs） |
| WebSearchPort | engines/search_ports.py:26 | ProviderWebSearchPort（引擎默认）+ HostWebSearchPort（deep_research/adapters:25-71） | 2.1 收敛后协议批次 3.7 删 |
| agent 5 端口 | engines/agent/ports.py:70-335 | Host*Port（features/agent/adapters 5 文件，降级为宿主助手类） | ToolContext 10 键（附录 D） |

## 附录 C：wiki 处置表（任务 4.1/4.2）

**wiki_routes 20 handler**：薄（12）= list_pages/get_page/search_pages/get_stats/get_ingest_status/get_revision/list_revisions/lint_wiki/auto_fix_wiki/list_issues/get_index(中)/get_page_sources(中) → 路由保留薄封装或直查读路径；中/厚（8）= create_page:278、update_page:325、delete_page:370、revert_page:476、rebuild_wiki:507、get_graph:554、create_issue:702、update_issue_status:739 → 下沉 service。9 处 db.commit（L321,366,387,499,548,681,735,764）+ rollback L364 随迁。辅助 3：_get_kb_or_404:76（改复用 validate_kb_access）、_to_list_item:89（留路由或进 schema 转换）、_finalize_links:391（进 graph service）。

**wiki_tools 8 工具**：_read_pages:289、_search:322、_write_page:353、_flag_issue:421、_replace_text:460、_rename_page:509、_read_issue:586、_update_issue:623 → 全部改调 4.1 service + access_service；删 _check_kb_access:250-276、_is_admin:278-285；5 处 db.commit（L408,451,499,576,649）随逻辑下沉。

## 附录 D：ToolContext 14 键处置表（ADR-6）

| 键 | 写入（chat_service） | 引擎消费 | 处置 |
|---|---|---|---|
| db_session/user_id/agent_id/session_id | L156-159 | user_id/agent_id 有消费（knowledge_search、memory、read_attachment）；db_session/session_id 引擎零消费 | 机制保留，值不变 |
| conversation_id | L161 | todo.py:102 | 保留 |
| tool_result_turn_budget | L162 | agent_engine:674,715 | 保留 |
| web_search_port | L166-170 | web_search.py:73 | 值改共享工厂产物 |
| knowledge_search_port | L171 | knowledge_search.py:165 | 值改宿主助手类 |
| attachment_read_port | L172 | read_attachment.py:73 | 同上 |
| memory_store_port / memory_search_port | L173-174 | memory.py:91,223,239 | 同上 |
| embedding_client_resolver | L175 | memory.py:240 | 保留（已是 callable） |
| subagent_runner | L181-192 | task.py:71；subagent/runner.py:76 置 None 防递归 | 保留 |
| approval_registry / event_sink | L196-197 | safety/approval.py:63,64 | 保留 |
| memory_limit_per_user_agent | 宿主未写入 | memory.py:131 默认值 | 保留现状 |

## 附录 E："单向依赖"文本清理清单（任务 1.3）

规范文本：根 CLAUDE.md:185；backend/CLAUDE.md:108-114（整节）。源码注释（7）：core/auth/__init__.py:4、core/auth/ports.py:5、shared/storage/attachment_presign.py:5、features/agent/adapters/attachment_read_adapter.py:6（文件 3.5 删，可跳）、engines/agent/agent_engine.py:109、engines/deep_research/{sources.py:9,types.py:6}（"分层铁律"字样）、engines/prompt_provider_adapter.py:12（文件 2.3 删）。导航文档：docs/project-structure-navigation.md:35。active 计划标注：agent-capability-enhancement-plan.md:262,275、agent-capability-pluggable-plan.md:106。历史文档（superpowers/、plans/historical）不改。**docs/transaction-boundary-conventions.md 不含此字样，不在清单内**。

## 附录 F：架构门禁测试处置表（批次 1/3）

| 文件 | 处置 |
|---|---|
| test_unidirectional_dependency_gate.py | 删（1.2） |
| test_core_auth_no_feature_imports.py | 删（1.2） |
| test_batch4_storage_seam.py | 改写：删"storage 零 features/setting import"守边断言；留 IndexSchema/AudioConfig 注入行为断言 |
| test_batch5b_model_config_seam.py（27 测试） | 大部分删（端口断言）；留 ModelCredentials re-export 兼容等行为项 |
| test_batch6a_seam_completion.py（15 测试） | "零 import"类删；留 rag_errors 异常树、ReviewStatus 同一性等子集 |
| test_auth_coverage_gate.py / test_knowledge_reorg_compat.py / test_openapi_contract_snapshot.py / test_openapi_response_name_determinism.py / test_source_encoding_gate.py | **全保留**（R6） |
| 新增 | test_no_cross_module_private_imports（0.4）、test_no_direct_httpexception（0.5）、test_import_acyclic_gate（1.1） |

## 附录 G：search_mode 11 处字面量清单（任务 4.8）

engines/agent/ports.py:98；engines/agent/tool/builtins/knowledge_search.py:118,275；features/agent/adapters/knowledge_search_adapter.py:158；features/deep_research/api/routes.py:178；features/deep_research/schemas/research_schema.py:51,59；features/evaluation/schemas/evaluation_schema.py:17；features/knowledge_space/api/search_routes.py:97；features/knowledge_space/models/knowledge_base.py:102（content_modes 列表）；另 qa/ai_chat_service.py:55（降级序列）。统一改 `SearchMode` 枚举（knowledge_space/schemas/search_schema.py:12）。
