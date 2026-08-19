# Agent 能力增强方案（子 agent 委派 / 中间件治理 / 危险审批 / 可观测性 / Plan-Execute）

## 1. 背景与目标

对比 OpenManus / deer-flow / hermes-agent / openclaw / opencode 五个开源 agent 项目后，NovaMind agent（ReAct + 5 内置工具 + 三层记忆 + docker 沙箱 + MCP）在「通用任务执行」维度有 5 个高价值缺口。本方案给出每个能力落地到 NovaMind 现有架构的具体设计，参考开源实现但不照搬框架。

> 本方案仅作实施底稿，不涉及代码改动。实施时以当前工作区为基线叠加。

---

## 2. NovaMind agent 现状与接入点

| 组件 | 文件 | 接入价值 |
|---|---|---|
| `AgentEngine.run` | `engines/agent/agent_engine.py:43` | ReAct 主循环，`yield AgentEvent`，`meta.total_tokens`，`max_iterations`，`compress_fn`。**loop_detection / 观测 turn span 接入点** |
| `ToolExecutor.execute` | `engines/agent/tool/executor.py:58` | before/after hooks 链 + 超时 + builtin/mcp 路由。**审批 / 观测 / budget hook 接入点** |
| `ToolHook` | `engines/agent/tool/hooks.py` | 已有 `LoggingHook` / `ResultTruncationHook`(8000 截断) / `ResultBudgetHook`(标记 oversized)。**新增 hook 的基类** |
| `BaseTool` + `ToolContext` | `engines/agent/tool/base.py` | 工具经 `context.get(key)` 取端口（`web_search_port`/`knowledge_search_port`/...）。**task 工具取 subagent_runner** |
| `AgentEvent` | `engines/agent/agent_engine.py:25` | SSE 事件：`content`/`tool_call`/`tool_result`/`reasoning`/`sources`/`done`/`error`/`context_overflow`。**新增事件类型** |
| `chat_service` 编排 | `features/agent/services/chat_service.py` | 装配 AgentEngine + 注入 context + SSE。**PlanningFlow / task runner / hooks 装配点** |
| `TodoTool` | `engines/agent/tool/builtins/todo.py` | 已有 4 态（pending/in_progress/completed/cancelled）。PlanningFlow 状态机可复用思路 |
| 三层记忆 | `engines/agent/memory/` | long_term + context_compressor + token_budget。plan 可持久化到记忆 |

---

## 3. 能力 1：子 agent 委派（task 工具）

**参考**：opencode `packages/opencode/src/tool/task.ts`

### 3.1 新增文件
- `engines/agent/tool/builtins/task.py` — `TaskTool(BaseTool)`
- `engines/agent/subagent/runner.py` — `SubAgentRunner`
- `engines/agent/subagent/__init__.py`

### 3.2 TaskTool schema
```python
{
  "description": str,        # 3-5 词短描述
  "prompt": str,             # 给子 agent 的详细任务
  "subagent_type": str,      # 预留：子 agent 类型（首版只 "general"）
  "session_id": Optional[str] = None,  # 续接已有子 session
}
```
返回：`<子 agent 最终文本回答>\n\n<task_metadata>\nsession_id: <id>\n</task_metadata>`（父 agent 可解析续接）。

### 3.3 SubAgentRunner
- 构造子 `AgentEngine` 实例（复用同一 `ToolExecutor`，但 `resolve_tools` 传**裁剪后**的 enabled_tools——exclude `task`/`todo`，防递归）
- 新 `session_id`（或复用传入的），独立 messages（只含 `prompt` 作 user message），**不继承父 ReAct 上下文**
- 跑完取最后一条 assistant text + 工具调用摘要 + 子 session_id 拼返回
- **递归控制**：子 agent 的 enabled_tools 不含 `task`（opencode 双重保险：权限 + 工具白名单；NovaMind 只需工具白名单）
- **并行**：`AgentEngine._process_tool_calls` 对同一消息多个 task tool_call 并行 `asyncio.gather`（需确认现有并行度，必要时改）
- **进度回流**：子 engine 的 `AgentEvent` 转发到父 SSE 流，`data` 加 `subagent_session_id` 标识；新增事件 `subagent_start`/`subagent_done`

### 3.4 装配
- `chat_service` 在 context 注入 `context["subagent_runner"] = SubAgentRunner(agent_engine, tool_executor, db, user_id, parent_session_id)`
- `TaskTool` 从 `context.get("subagent_runner")` 取 runner；未注入则返回"子 agent 未配置"

### 3.5 DB
- `agent_sessions` 表加 `parent_session_id VARCHAR NULL`（子 session 链路追溯）；`_run_schema_migrations` 幂等补列（参考已有钩子）
- 子 session 消息正常持久化到 `agent_messages`

### 3.6 风险
- 并行 task 的 SSE 事件交错：父流需带 subagent_session_id 区分，前端按 id 分流展示
- 子 agent token 消耗计入父 turn（观测要聚合）

---

## 4. 能力 2：loop_detection + tool_output_budget 中间件

**参考**：deer-flow `loop_detection_middleware.py` + `tool_output_budget_middleware.py`

### 4.1 tool_output_budget（先做，纯 ToolHook）
- 新增 `engines/agent/tool/hooks.py::ToolOutputBudgetHook(ToolHook)`
- 增强 `ResultTruncationHook`：按 **token 预算**（非字符）截断，head/tail 窗口吸附行边界
- 策略：`len(content) > threshold` → 保留 `head_chars` + `tail_chars`，中间插 `[... N chars omitted ...]`；`exempt_tools=["knowledge_search"]`（避免检索结果被截断丢关键来源）
- per-result 预算（非 per-turn），历史 ToolMessage 在下次 LLM 调用前复扫（防累积）——但 NovaMind 消息是 list，可在 `AgentEngine.run` 循环开头加一步 `_prune_historical_tool_outputs(messages, budget)`
- 装配：`ToolExecutor(hooks=[..., ToolOutputBudgetHook(threshold=12000, head=2000, tail=1000)])`，替换现有 `ResultTruncationHook`

### 4.2 loop_detection（后做，改 AgentEngine 循环）
- 新增 `engines/agent/middleware/loop_detection.py::LoopDetector`
- **两层检测**（抄 deer-flow）：
  - 第 1 层：工具调用集 hash（`_stable_tool_key` 显著参数分桶——`knowledge_search.query` / `web_search.query` 取 query，`code_execution` 取代码 hash；附近行号分桶避免 read_file 误判）
  - 第 2 层：单工具频率窗口（`deque` + `Counter`，同工具类型窗口内 N 次警告）
- 阈值：`warn=3` / `hard_stop=5` / `window=20`
- **动作**：
  - warn → 排队警告，下次 LLM 调用前注入 `HumanMessage` 提示"你重复调用相同工具，停止调用并给出最终答案"（**不在 after_model 插入**，避免破坏 tool_call 配对——NovaMind 在循环开头注入）
  - hard_stop → 清空当次 LLM 响应的 tool_calls，强制进入最终摘要
- 数据结构：`_history: OrderedDict[session_id, list[hash]]` LRU + `_warned: set` + `_tool_name_history: deque`，线程/会话级，受 lock 保护
- 接入点：`AgentEngine.run` 循环内，`_process_tool_calls` 后调 `detector.track(session_id, tool_calls)`；循环开头 `detector.drain_warnings(session_id)` 注入 messages
- 装配：`AgentEngine.__init__` 加 `loop_detector: Optional[LoopDetector]`，`chat_service` 注入

### 4.3 风险
- loop_detection 改 AgentEngine 核心循环，要保证不破坏现有 SSE 流和 compress_fn 逻辑
- 显著参数分桶需按 NovaMind 工具调参（knowledge_search/web_search/code_execution）

---

## 5. 能力 3：危险操作审批

**参考**：hermes `tools/approval.py`（三层模式 + 智能审批 + allowlist）

### 5.1 新增文件
- `engines/agent/safety/approval.py` — 危险模式检测 + 审批门
- `engines/agent/safety/patterns.py` — `HARDLINE_PATTERNS` + `DANGEROUS_PATTERNS`
- `features/agent/api/approval_routes.py` — 用户审批决策端点（异步审批回传）

### 5.2 检测范围
NovaMind 危险操作集中在 `code_execution` 工具的代码内容（+ 未来 shell 工具的命令）。检测对象是 `arguments["code"]`（code_execution）的字符串。
- `HARDLINE_PATTERNS`（不可绕过）：`rm -rf /`、`mkfs`、`dd of=/dev/sd`、fork bomb、`shutdown/reboot`、`os.system("rm -rf")`、`subprocess` 调危险命令
- `DANGEROUS_PATTERNS`（可绕过）：`chmod 777`、`DROP TABLE`、`> /etc/*`、`curl|sh`、`git push --force`、`os.remove` 递归、写 `~/.ssh/`
- 检测逻辑：正则 + 结构化 token 检测（`subprocess.run(["rm",...])` / `os.popen` / `eval`）

### 5.3 审批门（ApprovalHook）
- 新增 `engines/agent/tool/hooks.py::ApprovalHook(ToolHook)`
- `before_execute`：对 `code_execution` 工具，`detect_dangerous_command(arguments["code"])`
  - HARDLINE → 直接拒绝，返回 `ToolResult(status=ERROR, content="已阻止：...")`（fail-closed）
  - DANGEROUS → 触发审批流
  - 安全 → 放行
- 审批流（异步，难点）：
  1. 生成 `approval_id`，存 `_pending[approval_id] = {event: asyncio.Event, ...}`
  2. yield `AgentEvent("approval_request", {"approval_id", "tool", "command_preview", "pattern_key"})` 到 SSE
  3. `await event.wait(timeout=120s)` 阻塞工具执行
  4. 前端用户决策 → POST `/agent/approval/{approval_id}` `{decision: approve_once|approve_always|deny}` → set event
  5. 超时 → deny（fail-closed）
- **难点**：`ToolHook.before_execute` 是 await 的，可阻塞；但 SSE 事件 yield 在 AgentEngine.run，不在 ToolExecutor。需要 ToolExecutor 能向 AgentEngine 发事件——可给 ToolExecutor 加一个 `event_sink` 回调，hook 触发时调 `event_sink(AgentEvent)`，AgentEngine.run 把 sink 的事件 yield 出去
- **简化首版**：只做检测 + HARDLINE 拒绝 + DANGEROUS 日志告警 + SSE `approval_request` 事件（前端展示但不阻塞），工具仍执行。异步阻塞审批作为二期

### 5.4 allowlist + 智能审批（二期）
- `approve_always` → 持久化 pattern_key 到 `agent_approval_allowlist` 表（user_id + pattern_key）
- 智能审批：辅助 LLM（用 `model_config_service` 降级 LLM）判断低风险自动批准，参考 hermes `_smart_approve`（去注释 + XML 包裹 + system prompt 防注入）

### 5.5 风险
- 异步审批需前端配合（新端点 + SSE 处理），首版建议先做"检测+拒绝+告警"
- 代码内容检测的误报率需调参（code_execution 跑测试代码可能含 `rm` 字符串但不危险）

---

## 6. 能力 4：可观测性（token/cost + trace）

**参考**：hermes `usage_pricing.py`（per-message 统计）+ openclaw `diagnostics-otel`（OTel 导出）

### 6.1 token/cost 统计
**现状**：`AgentEngine.run` 已累计 `meta.total_tokens`，`done` 事件含 `total_tokens`/`tool_calls_count`。但无 per-field 拆分、无 cost、无持久化。

**新增**：
- `shared/ai_models/usage.py` — `CanonicalUsage` dataclass + `normalize_usage(raw_usage) -> CanonicalUsage`（归一化 Anthropic/OpenAI/DeepSeek 三种 usage 形态，参考 hermes）
- `engines/agent/observability/usage_tracker.py` — `UsageTracker`：累计 per-turn usage + 算 cost
- 价格表：`setting/yaml_config/yaml/*.example` 加 `model_pricing` 段（per-model input/output/cache per-million），或新表 `model_pricing`（user_id NULL = 全局）
- DB 新表 `agent_usage`：`id/session_id/turn_index/input_tokens/output_tokens/reasoning_tokens/cache_read/cache_write/cost_usd/model/timestamp`

**接入**：
- `AgentEngine._run_iteration_stream` 已有 `meta`，扩展 meta 记录 `usage: CanonicalUsage`（从 LLM 响应 chunk 的 usage 归一化）
- `done` 事件 data 加 `usage_breakdown` + `cost_usd`
- `chat_service` 在 done 后写 `agent_usage` 表（repository）
- 观测 hook：`engines/agent/tool/hooks.py::UsageRecordHook`（after_execute 记工具 duration，可选）

### 6.2 OTel trace
**新增** `engines/agent/observability/tracing.py`：
- `start_turn_span(session_id, user_query) -> span`（turn 级 span）
- `start_tool_span(tool_name, arguments) -> span`（工具子 span，在 ToolExecutor.execute 前后）
- SSE 事件 → span events（`tool_call`/`content`/`done`）
- Python `opentelemetry-sdk` + `OTLPSpanExporter`，配置 `otel.endpoint` 在 yaml
- 接入：`AgentEngine.run` 开 `turn_span`，`ToolExecutor.execute` 开 `tool_span`（可做成 `TracingHook`）
- 可选 Prometheus 指标：`agent_turn_total` / `agent_tool_calls` / `agent_tokens_total` / `agent_turn_duration_seconds`

### 6.3 trajectory（可选）
- `engines/agent/observability/trajectory.py` — ShareGPT JSONL 存文件（成功/失败分文件），参考 hermes `trajectory.py`
- 自动 secret redaction：复用 `shared/utils/redact`

### 6.4 风险
- 价格表维护成本（model 多，价格变动）；首版可只记 tokens，cost 用估算标记 `status="estimated"`
- OTel 引入新依赖 `opentelemetry-sdk`，需加到 `pyproject.toml`

---

## 7. 能力 5：Plan-and-Execute

**参考**：OpenManus `app/flow/planning.py` + `app/tool/planning.py`

### 7.1 新增文件
- `engines/agent/flow/base.py` — `BaseFlow` 抽象（持有 agent_engine + tool_executor）
- `engines/agent/flow/planning_tool.py` — `PlanningTool(BaseTool)`，7 command
- `engines/agent/flow/planning_flow.py` — `PlanningFlow(BaseFlow)`
- `engines/agent/flow/prompts.py` — planning system/next-step prompt

### 7.2 PlanningTool
- 7 command：`create`/`update`/`list`/`get`/`set_active`/`mark_step`/`delete`
- schema 抄 OpenManus `tool/planning.py:22-67`
- 状态机 4 态：`not_started`/`in_progress`/`completed`/`blocked`（符号 `[ ]`/`[→]`/`[✓]`/`[!]`）
- 存储：内存 dict `plans`（key=plan_id），**持久化到三层记忆**（long_term）或新表 `agent_plans`
- `update` 动态重规划：按"位置+文本完全匹配"保留已完成状态（抄 OpenManus `_update_plan`）
- 进度：`completed/total*100`

### 7.3 PlanningFlow（双层循环）
```
PlanningFlow.execute(input_text, ...):
  _create_initial_plan(input_text)     # 独立 LLM 调用 + PlanningTool 生成计划
  while True:
    idx, step = _get_current_step()    # 取第一个 not_started/in_progress
    if idx is None:
      result += _finalize_plan(); break
    mark_step(idx, in_progress)
    yield AgentEvent("plan.step_started", {step_index, step, plan_status})
    step_prompt = _build_step_prompt(plan_status, step)
    async for event in agent_engine.run(step_prompt, ...):  # 内层 ReAct
      yield event  # 转发子 ReAct 事件
    mark_step(idx, completed)
    yield AgentEvent("plan.step_completed", {step_index, plan_status})
  yield AgentEvent("plan.completed", {summary})
```
- **Flow 包 AgentEngine，不替代**：每步调 `AgentEngine.run(step_prompt)` 复用现有 ReAct + ToolRegistry + SSE
- 步骤路由：正则 `\[([A-Z_]+)\]` 抽 step type → agent registry（NovaMind 首版单 agent，都用 primary，路由预留）
- `_create_initial_plan`：独立 LLM 调用（非 agent）+ PlanningTool 作 tool，`tool_choice=AUTO`，让 LLM 生成 tool_call 创建计划
- `_finalize_plan`：LLM 生成总结

### 7.4 装配
- `chat_service` 加 `plan_mode: bool`（Agent 配置 `extra_config.plan_mode` 或请求参数）
- `plan_mode=True` → 用 `PlanningFlow.execute` 包 `AgentEngine.run`；`False` → 现有 ReAct
- PlanningTool 注册到 ToolRegistry，plan_mode 时加入 enabled_tools

### 7.5 SSE 新事件
`plan.created` / `plan.step_started` / `plan.step_completed` / `plan.completed`，data 含 `plan_id`/`step_index`/`plan_status`/`progress`

### 7.6 风险
- 双层循环的 SSE 事件流交织（plan.* + 子 ReAct 的 content/tool_call），前端需区分层级展示
- PlanningFlow 改 chat_service 编排主流程，风险高，建议放最后做
- 计划生成失败兜底（LLM 没调 planning tool → 默认 3 步）

---

## 8. 实施顺序与依赖

按「性价比 + 依赖」排序，每个能力独立可提交：

| 批次 | 能力 | 难度 | 依赖 | 价值 |
|---|---|---|---|---|
| **E1** | 可观测性 token/cost（6.1） | 中 | 无 | 基础，后续都能看消耗 |
| **E2** | tool_output_budget hook（4.1） | 低 | 无 | 防上下文撑爆，纯 hook |
| **E3** | loop_detection（4.2） | 中 | E2 同类 | 防卡死，改 AgentEngine 循环 |
| **E4** | 危险审批-检测+拒绝（5.3 简化版） | 中 | 无 | 安全合规，无前端配合 |
| **E5** | 危险审批-异步审批（5.3 完整 + 5.4） | 高 | E4 + 前端 | 完整审批流 |
| **E6** | 子 agent 委派（能力 1） | 中高 | E1（观测聚合） | 复杂任务并行 |
| **E7** | Plan-and-Execute（能力 5） | 高 | E6 可选 | 规划型 agent |
| **E8** | OTel trace + Prometheus（6.2） | 中 | E1 | 企业部署可观测 |

**建议路径**：E1 → E2 → E3 → E4 → E6 → E7 → E5 → E8（E5/E8 按需）

---

## 9. 验证清单

每个批次独立验证：
- [ ] E1：`agent_usage` 表写入；`done` 事件含 `usage_breakdown` + `cost_usd`；多 provider usage 归一化正确
- [ ] E2：工具输出超 threshold 截断 + head/tail + 行边界吸附；`knowledge_search` 豁免
- [ ] E3：连续重复工具调用 3 次注入警告；5 次硬停 + 最终摘要；不同参数不误判
- [ ] E4：HARDLINE 命令直接拒绝；DANGEROUS 命令 SSE `approval_request` 事件 + 日志；安全命令放行
- [ ] E5：`approval_request` → 前端决策 → 工具继续/拒绝；超时 deny；`approve_always` 持久化
- [ ] E6：task 工具启动子 agent；子 agent 不含 task 工具（防递归）；子 session `parent_session_id`；SSE 事件带 subagent_session_id；并行多 task
- [ ] E7：plan_mode 生成计划；步骤逐个执行 + mark_step；动态重规划保留已完成；`plan.*` SSE 事件；进度百分比
- [ ] E8：OTel span 导出（turn + tool 子 span）；Prometheus 指标暴露

每批次：`pytest` 相关测试 + 单向依赖门禁 + 手动 SSE 验证。

---

## 10. 兼容性与风险总览

| 风险 | 级别 | 缓解 |
|---|---|---|
| AgentEngine 循环改动（E3/E7）破坏 SSE/compress_fn | 高 | 充分单测 + 保留旧路径开关 |
| 异步审批阻塞工具（E5）需前端配合 | 中 | 首版做检测+拒绝，异步审批二期 |
| 子 agent SSE 事件交错（E6） | 中 | 事件带 subagent_session_id，前端分流 |
| OTel 新依赖（E8） | 低 | 可选启用，yaml 开关 |
| 价格表维护（E1） | 低 | cost 标 `status=estimated`，tokens 为准 |
| 单向依赖铁律 | — | 新模块归 engines/（纯逻辑），装配在 features/，门禁守护 |