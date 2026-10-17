# Agent 长期记忆接入 Mem0 设计方案

- 状态：P0 PoC 已通过（2026-10-16），P1 待实施
- 日期：2026-10-16
- 范围：`backend/src/engines/agent/memory/`、`backend/src/features/agent/`、`backend/src/setting/`
- 前置调研：市面方案对比（Mem0 / Zep / Letta / Cognee / Memobase）结论见文末附录

## 0. P0 PoC 结论（2026-10-16 实测，mem0ai 2.2.1）

**三连通全部打通**：mem0ai AsyncMemory → 自研网关（LLM 提取，glm-5.3-flash）+ dashscope embedding（qwen3.7-text-embedding-flash，1024 维）+ 本机 ES 9.3.2。`add()` 产出事件、ES 索引落库、metadata 过滤检索、按 memory_id 删除全部验证通过。

实测确认的关键事实（写代码时必须遵守）：

| # | 事实 | 对设计的影响 |
|---|---|---|
| 1 | **mem0ai 2.2.1 依赖 openai 3.31.0，其传输层是 httpx2（不是 httpx）**，header 值强制 ascii 编码 | api_key 解密产物必须纯 ASCII；`Mem0Reconciler` 构造后应自检 |
| 2 | ES provider 拼 `host:port`，host 带端口号会变成 `9200:9200` | 配置 host 不带端口，port 单独传 |
| 3 | 网关**没有** `/v1/embeddings`（只有 chat/completions） | D4 确认：embedder 必须走用户模型配置的原始连接参数（dashscope 等），LLM 走网关 |
| 4 | `user_model_configs.model_type` 是**整数枚举**（1=llm，2=embedding） | D4 的 `get_model_connection_params` 按 int 枚举查 |
| 5 | 事件返回结构：`{"results": [{"event": "ADD", "memory": "...", "id": ...}]}`（v1.1 模式）；冲突改写实测产出**新 ADD 而非 UPDATE**（v1.1 简化调和） | 防御性解析按 `results[].event` 设计；UPDATE/DELETE 事件处理保留但观测到主要事件流是 ADD |
| 6 | `search/get_all` 用 `filters={"user_id":..., "agent_id":...}` + `top_k`；`delete_all` 反而用顶层 `user_id=`（API 风格不统一） | Reconciler 封装层吸收 API 差异 |
| 7 | metadata 过滤隔离性验证通过（错误 user 检索 0 命中） | 单 collection + metadata 过滤方案**可行**（开放问题 2 定案） |
| 8 | ES 索引字段：`text` / `vector`(dense_vector) / `metadata`(user_id/agent_id/data/hash/text_lemmatized) | 对齐现有 `agent_memories.extra_data.mem0_id` 映射；hash 字段是 mem0 去重依据 |
| 9 | LLM 网关对 mem0 的提取 prompt（json_object + 中文）响应正常 | 网关无需改造 |
| 10 | 独立进程解密必须先 `configure_encryption_key(get_config().security.encryption_key)`，否则静默解出乱码 | D4 的连接参数必须走启动期已装配的 ModelConfigService，禁止裸调 decrypt |

PoC 环境残留清理：`mem0_poc` / `mem0migrations` 索引已删；`C:/tmp/nm_e2e/mem0env` 会话级临时保留。

## 1. 背景与目标

现有长期记忆系统（`engines/agent/memory/long_term.py`）已具备：MySQL（真源）+ ES hybrid 召回（KNN+BM25 RRF）、压缩时记忆抢救提取、memory 工具主动写入、注入攻击安全扫描、prompt-cache 友好的冻结快照。

**能力缺口**（本方案要补的）：

| 缺口 | 现状 | 位置 |
|---|---|---|
| 语义去重 | 同类别同内容**精确匹配**去重，同义不同文会重复累积 | `host_memory_store.py:93` `find_similar` |
| 冲突消解 | 无。用户新偏好覆盖旧偏好时新旧两条并存 | `long_term.py:208` `consolidate` |
| 会话结束巩固 | 仅上下文压缩触发提取，短会话（不压缩）零记忆产出 | `context_compressor.py:184` |
| 记忆更新追踪 | replace 只按子串定位、无新旧值调和 | `long_term.py:112` |

**Mem0 恰好补前两个**：其 extract-and-reconcile 管线对每批新事实与存量比对，由 LLM 产出 `ADD / UPDATE / DELETE / NOOP` 事实操作，天然实现语义去重与冲突消解。

**本方案不引入的**：Mem0 作为读取/检索层（现有 ES hybrid 保留）、Mem0 作为存储真源（MySQL 保留）、Zep 的时序图谱（非痛点）。

## 2. 总体架构

核心定位一句话：**Mem0 是写入期的「提取+调和」引擎，不是存储；读取链路零改动。**

```
对话轮次结束（压缩触发）
        │
        ▼
LongTermMemory.consolidate()          ← 接口签名不变
        │
        ├── backend=mem0（新）
        │     ▼
        │   Mem0Reconciler.add(messages)      ← Mem0 管线：
        │     │   1. LLM 提取候选事实
        │     │   2. 对其工作存储做相似检索
        │     │   3. LLM 调和 → ADD/UPDATE/DELETE 事件流
        │     ▼
        │   事件应用器（新，Mem0Reconciler 内）
        │     ├─ ADD    → 安全扫描 → 上限检查 → MySQL create(extra_data.mem0_id) → ES 索引
        │     ├─ UPDATE → 安全扫描 → 按 mem0_id 定位 → MySQL update → ES 重索引
        │     ├─ DELETE → 按 mem0_id 定位 → MySQL delete → ES 删文档
        │     └─ NOOP   → 忽略
        │
        └── backend=builtin（现状，保留为降级路径）
              ▼
            LLM 提取 + find_similar 精确去重 + store()

读取（完全不动）：
  冻结快照  memory_manager.build_frozen_snapshot → MySQL list_by_agent 前 20 条
  动态预取  memory_manager.prefetch → long_term.search → ES hybrid → MySQL LIKE 降级
  管理端点  GET/DELETE /agents/{id}/memories → MySQL
```

Mem0 自身的工作存储（我们配置为 ES 的一个独立 collection）**只服务于 Mem0 调和时的相似比对**，不对外提供检索；可随时从 MySQL 真源回灌重建。

## 3. 关键设计决策

### D1：Mem0 只做写入管线，MySQL 仍是 source-of-truth

备选是被 Mem0 全权接管存储，否决理由：
- 冻结快照、管理 API、50 条上限、access_count 全部要重做；
- 读取链路是验证过的资产（RRF 混合召回、维度自愈、TTL 缓存字节恒定），换掉收益为零；
- Go 迁移分支（`refactor/go-migration`）将来接管 agent 引擎时，MySQL+ES 产物是跨语言资产——只有写入管线绑 Python SDK，Go 侧可复刻调和逻辑或保留 Python sidecar，**迁移叙事不被 Mem0 绑架**。

### D2：Mem0 ↔ MySQL 映射用 `agent_memories.extra_data.mem0_id`

`extra_data` JSON 列已存在（`features/agent/models/memory.py:18-51`），**无需迁移**。

- ADD 事件：MySQL create 后把 Mem0 返回的 memory id 写入 `extra_data.mem0_id`；
- UPDATE/DELETE 事件：按 `extra_data.mem0_id` 精确定位 MySQL 行；
- 悬空兜底（Mem0 collection 重建后 id 失配）：`UPDATE/DELETE` 按 `find_by_content_contains` 内容子串二跳定位；仍找不到则**放弃该事件 + warning**——失败方向是「不动真源」而非误写。

### D3：安全扫描与上限检查仍前置，不信任 Mem0 输出

Mem0 是第三方 LLM 管线，其产出的事实文本必须过与人工写入完全相同的门禁：

- `scan_memory_content()`（注入攻击/不可见 Unicode 扫描）拦截则跳过该事件；
- ADD 应用前查该 (agent_id, user_id) 记忆总数，超 50 条上限则拒绝 ADD（与 memory 工具 `builtins/memory.py:142` 同口径）。

### D4：LLM / embedder 参数解析——按请求现配 + LRU

Mem0 的 `AsyncMemory.from_config()` 在构造时固定 LLM/embedder 的 `base_url / api_key / model`，而本平台模型配置是**按用户**的（`model_config_service.get_user_default_model_name`）。三个备选：

- (a) 每 (user, agent) 维度缓存 Mem0 实例——模型配置变更失效逻辑复杂，否决；
- (b) 全局固定一套 Mem0 专用模型——跨用户体验不一致，且违背「没选不兜底」原则，否决；
- **(c) 采用**：consolidate 是冷路径（仅压缩时触发），每次按该用户当前默认 LLM/embedding 模型的**原始连接参数**现构造 `AsyncMemory`，以 `(base_url, model, api_key指纹)` 为键做小 LRU（16）避免同用户反复握手。

需要 `ModelConfigService` 补一个「取模型原始连接参数（base_url/api_key 明文/model 名）」的方法（见 §5 改动清单）。api_key 解密后只在进程内传给 Mem0，**禁止落日志**。

### D5：失败降级——Mem0 任何失败回退 builtin 提取路径

| 故障 | 行为 |
|---|---|
| `backend: mem0` 但 mem0ai 未安装 / ES 不可达 / LLM 参数缺失 | 启动装配时 warning，运行期用 builtin |
| `Mem0Reconciler.add()` 抛异常 / 事件解析失败 | 单次 warning，本次 consolidate 降级 builtin |
| Mem0 ADD/UPDATE 事件应用时 ES 索引失败 | MySQL 已写、ES 仅告警（与现状 `_index_to_es` 同语义） |

现有 `consolidate()` 内核整体保留为 `_consolidate_builtin()`，是降级路径也是对照实现。

### D6：会话结束巩固作为独立开关，默认关

Mem0 逐轮 add 很轻，但会让记忆产出频率大增（行为变化），第一版不动触发时机（仍只压缩时触发）。yaml 预留：

```yaml
agent:
  memory:
    backend: builtin            # builtin | mem0
    on_turn_done: false         # 阶段 3：每轮 done 后异步巩固最近 2 轮
```

`on_turn_done: true` 时在 `chat_service._handle_done`（`chat_service.py:1602`）commit 之后 fire-and-forget 调 consolidate（独立 db session，失败仅告警，绝不阻塞/连坐对话流）。

### D7：依赖放 optional extra

`mem0ai` 加 `backend/pyproject.toml` 的 `[project.optional-dependencies]`（新增 `mem0` extra），对齐 `transformers`/`deepdoc-vision` 惯例——backend=builtin 的部署零新增依赖。

## 4. 配置设计

```yaml
# default.example → agent 节新增 memory 子节
agent:
  memory:
    backend: builtin              # builtin | mem0
    es_collection: novamind_mem0  # Mem0 工作存储的 ES collection 名
    history_size: 5               # 调和时 Mem0 参考的存量相似记忆条数
    on_turn_done: false           # 每轮结束巩固（阶段 3）
    lru_size: 16                  # AsyncMemory 实例缓存数
```

- **不新增 .env**：ES 连接复用现有 ES 配置；LLM/embedder 走用户模型配置（D4）。
- `AgentConfig`（`setting/yaml_config/config.py:308`）加 `memory: AgentMemoryConfigYaml` 强类型段，零值即现状（builtin），**向后兼容**。

## 5. 改动清单（文件级）

| # | 文件 | 动作 |
|---|---|---|
| 1 | `backend/src/engines/agent/memory/mem0_reconciler.py` | **新增**。`Mem0Reconciler`：包装 AsyncMemory 构造（D4 LRU）、`reconcile(messages, agent_id, user_id, conversation_id) -> 事件应用`、事件解析（防御性，schema 变更只改此处）、ADD/UPDATE/DELETE 应用到 store/search port（D2/D3） |
| 2 | `backend/src/engines/agent/memory/long_term.py` | `consolidate()` 改为按注入的 reconciler 分派；现内核改名 `_consolidate_builtin()` 作降级路径；`__init__` 加 `reconciler=None` 可选参 |
| 3 | `backend/src/features/agent/services/chat_service.py` | `_create_memory_manager`（L552）按 yaml 配置构造 `Mem0Reconciler` 传入 MemoryManager；新增 `_build_memory_reconciler(user_id)`（含模型原始参数解析） |
| 4 | `backend/src/features/agent/services/model_config_service.py` | 新增 `get_model_connection_params(user_id, model_type) -> {base_url, api_key, model}`（解密 api_key；Mem0 专用，勿复用到日志） |
| 5 | `backend/src/engines/agent/memory/memory_manager.py` | `create()` 工厂透传 reconciler 至 LongTermMemory |
| 6 | `backend/src/setting/yaml_config/config.py` + `yaml/default.example` | `AgentMemoryConfigYaml` dataclass + example 注释（§4） |
| 7 | `backend/pyproject.toml` | `[project.optional-dependencies]` 加 `mem0 = ["mem0ai>=<PoC 验证版本>"]` |
| 8 | `backend/tests/engines/agent/test_mem0_reconciler.py` | **新增**，见 §7 |
| 9 | `backend/src/engines/agent/memory/DESIGN.md` | 追加「Mem0 调和管线」一节 |
| 10 | `docs/plans/active/agent-mem0-integration-plan.md` | 本文档 |

**明确不动的**：`interfaces.py`（ILongTermMemory 契约不变）、`host_memory_store.py` / `host_memory_search_port`、`memory_search_repository.py`（ES hybrid）、`builtins/memory.py`（工具路径阶段 1 不接 Mem0）、前端全部、`agent_memories` 表结构。

## 6. 一致性运维（三个必须覆盖的联动点）

1. **管理 API 删除联动**：`DELETE /agents/{agent_id}/memories*`（`api/routes.py:604-642`）删 MySQL 后，若 `extra_data.mem0_id` 存在则同步 `mem0.delete(memory_id)`——否则 Mem0 工作存储残留幽灵记忆，后续调和会基于已删记忆产出错误 UPDATE。
2. **回灌工具**：`Mem0Reconciler.rebuild_from_mysql(agent_id, user_id)`——按 `list_by_agent` 全量 `mem0.add`（带 `metadata`），产出新 mem0_id 后**回写** MySQL `extra_data.mem0_id`。用于 collection 损坏/换 embedding 维度后重建。阶段 1 以内部函数+手动触发交付，不暴露端点。
3. **access_count 语义**：Mem0 调和过程中对其存储的检索**不**计入 MySQL access_count（那是用户侧召回热度指标，机器内部比对不算）。

## 7. 测试计划

单测（`tests/engines/agent/test_mem0_reconciler.py`，fake AsyncMemory，不依赖真 ES/LLM）：

1. **事件映射三例**：ADD → `store.create` 且 `extra_data.mem0_id` 正确；UPDATE → 按 mem0_id 定位且 `update_content`；DELETE → 按 mem0_id 定位且 `delete`+ES 删除。
2. **正反两用例**（补丁原则）：
   - 反：事件文本含注入 payload → `scan_memory_content` 拦截，MySQL 零写入；
   - 反：ADD 超上限 → 拒绝；相邻正常 ADD 不受影响；
   - 反：mem0_id 悬空且内容匹配失败 → 放弃 + warning，MySQL 不动。
3. **降级**：reconciler 抛异常 → `_consolidate_builtin` 接管并产出记忆（现有断言复用）。
4. **防御性解析**：Mem0 返回缺字段/非 list → 空 + warning，不抛。
5. **现有测试全绿**：`test_memory_search_dim_self_heal.py`、`test_knowledge_pipeline_batch2.py`、compressor 系列不破。

集成验证（手动，:8100 起服务后）：

- 同义改写不重复：对同一偏好换两种说法问两轮 → `agent_memories` 仅 1 条且内容为调和后版本；
- 冲突消解：「我用 MySQL」→「我换 PostgreSQL 了」→ 旧条被 UPDATE 而非并存；
- 短会话回归：不触发压缩的会话，记忆产出行为与现状一致（阶段 1 未开 on_turn_done）。

## 8. 分阶段实施

| 阶段 | 内容 | 出口判据 |
|---|---|---|
| **P0 PoC（半天）** | venv 装 mem0ai，脚本验证三连通：mem0ai + 本机 ES（:9200，注意 elasticsearch 9.x 客户端兼容性）+ 自研网关 `openai_base_url`；确认 `add()` 返回的事件结构（id/event/data 字段名以实测为准，§5-1 防御性解析按实测写） | 一次 add 产出 ADD 事件且 ES collection 可查 |
| **P1 核心管线（1-2 天）** | §5 改动 1-8；`backend: builtin` 默认，mem0 可切换；全部单测 | 测试计划 §7 全绿 |
| **P2 行为验证** | E2E 三个场景（§7 集成验证）+ 管理删除联动 + 回灌演练 | 真实对话验证通过 |
| **P3（可选，另立计划）** | `on_turn_done` 轮末巩固；memory 工具 add 走调和（语义去重工具化）；衰减/淘汰（access_count/last_accessed 加权——与 Mem0 无关的独立线） | 单独评审 |

## 9. 风险与开放问题

| 风险 | 等级 | 缓解 |
|---|---|---|
| ~~mem0ai 对 Elasticsearch 9.x 的 provider 兼容性未实测~~ → **已实测通过**（mem0ai 2.2.1 + elasticsearch 9.5.1 客户端 + ES 9.3.2 服务端） | 已消除 | — |
| ~~mem0ai 依赖 openai 3.31 与主项目 openai 2.14 同进程冲突~~ → **已消除（2026-10-16）**：主项目已升级 `openai>=3.31.0` 并通过全仓验证（ai_models 162 单测 + 网关 E2E 非流式/流式/工具调用 + 测试子集 1020+ 绿），embedded 方案（mem0ai 直装）可行，无需 REST server 模式 | 已消除 | — |
| Mem0 事件返回结构无版本契约，升级可能 break | 中 | 防御性解析收敛在 Mem0Reconciler 单文件 + §7-4 测试（事件结构已实测入档 §0-5） |
| 每次调和多 1-2 次 LLM 调用（提取+调和） | 低 | 冷路径异步，不占对话延迟；auxiliary LLM 可指定便宜模型 |
| 双份存储（Mem0 collection + agent_memory_* 索引）ES 占用翻倍 | 低 | 记忆量级（50/用户×agent）极小；§6-2 可重建 |
| api_key 明文流经 Mem0 配置对象 | 低 | 进程内传递；mem0 适配层禁止任何日志输出 config；httpx2 ascii 约束已在 PoC 断言 |
| ~~Go 迁移分支无 mem0ai 对应物~~（原 REST server 模式的附带优势随冲突消除失效） | 信息 | Go 侧可复刻调和逻辑或保留 Python sidecar（见 D1） |

开放问题（P0 后状态）：

1. ~~Mem0 的 `user_id/agent_id` 双键过滤在 ES provider 下的 filter 实现是否高效~~ → 已实测：KNN + metadata term pre-filter 工作正常，隔离性 0 泄漏；
2. ~~`es_collection` 按 agent 分索引还是单 collection~~ → **定案：单 collection + metadata 过滤**（Mem0 原生用法，PoC 验证通过）；
3. （新增）实测 v1.1 模式下冲突改写产出 ADD 而非 UPDATE——如需真正的 UPDATE/DELETE 调和，要评估 `version: "v2"` 模式（含事实级调和）；P1 实施时先按 v1.1 简化模型（新增+hash 去重），冲突消解作为 P3 增强。

## 附录：选型调研结论（2026-10-16）

| | Mem0 | Zep/Graphiti | Letta | Cognee | Memobase |
|---|---|---|---|---|---|
| 定位 | 记忆层 SDK | 时序知识图谱引擎 | 完整 agent 运行时 | 图谱 ECL 管道 | 用户画像+时间线 |
| 许可 | Apache-2.0 | Apache-2.0（**Zep CE 已废弃**） | Apache-2.0 | Apache-2.0 | Apache-2.0 |
| 自托管 | 纯 SDK 内嵌 | 需 Neo4j/FalkorDB | Docker+Postgres 服务 | 内嵌 | Docker 服务 |
| ES 后端 | ✅ 官方支持 | ✗（图库） | ✗ | ✗ | ✗ |
| 采用度 | ~63K★ 最广 | ~30K★ | ~24K★ | ~30K★ | 较小 |

否决理由摘要：Zep——自托管只剩 Graphiti 引擎需自建周边+Neo4j，时序推理非企业知识库痛点；Letta——接管整个 agent 运行时，等于放弃自研 `engines/agent`；Cognee/Memobase——需引入自带存储栈，且调和能力弱于 Mem0 的 ADD/UPDATE/DELETE 事实操作模型；LangMem——绑死 LangGraph。各厂商 LoCoMo/LongMemEval benchmark 互相矛盾且均为自发布，不作为选型依据。
