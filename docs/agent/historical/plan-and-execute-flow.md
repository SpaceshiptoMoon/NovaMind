# Plan-and-Execute（PlanningFlow）完整流程说明

> 适用于 2026-09-29 主线（commit `4a1600a`），覆盖六批次修复后的最终形态。
> 核心代码：`backend/src/engines/agent/flow/planning_flow.py`（引擎编排）、
> `backend/src/features/agent/services/chat_service.py`（持久化与事件接线）、
> `frontend/src/components/agent/PlanCard.vue`（计划卡渲染）。

---

## 一、怎么启用

创建/编辑智能体时打开「**计划模式**」开关（写入 `extra_config.plan_mode = true`）。
对话时 `chat_service` 读到该标志，把本轮请求交给 `PlanningFlow`，而不是直接跑普通 ReAct 循环。

---

## 二、全流程图

```
用户开「计划模式」建 Agent
        │
        ▼
┌─ 发消息 ──────────────────────────────────────────────┐
│ chat_service 读 extra_config.plan_mode                │
│   true → PlanningFlow.execute()（不再直接跑 ReAct）    │
└──────────────────────────────────────────────────────┘
        │
        ▼
① 外层规划  _create_initial_plan()
   LLM + json_object 生成 {"title", "steps":[...]}
   ├─ 合法 JSON（含空 steps）→ 原样透传
   └─ 解析失败/异常 → 默认 3 步兜底（query[:80]）
        │  yield plan.created {title, steps}
        ▼
② chat_service 落库计划骨架
   _handle_plan_created()：建 role=plan 消息
   extra.plan = {title, steps, statuses: 全 not_started}
        │
        ▼
③ 逐步执行循环（for i, step in enumerate(steps)）
   ┌────────────────────────────────────────────┐
   │ statuses[i]=in_progress → plan.step_started │
   │                                            │
   │ 组装本步上下文（浅拷贝！不污染基础列表）：      │
   │   基础 messages                             │
   │   + 「此前步骤产出」块（每步头400+尾1000节选）  │
   │   + 本步 prompt（带 [✓]/[→] 状态符号）       │
   │                                            │
   │ 内层 AgentEngine.run() ← 真 ReAct 循环      │
   │   LLM ↔ 工具多轮，流式事件原样透传           │
   │   iteration 由 chat_service 加全局偏移写回    │
   │                                            │
   │ 收集内层 done：                             │
   │   聚合 usage / tool_calls / iterations      │
   │                                            │
   │ ├─ 成功 → statuses[i]=completed             │
   │ │         → plan.step_completed             │
   │ └─ truncated/error/overflow →               │
   │    statuses[i]=blocked → plan.step_failed   │
   │    → break（fail-fast 中断，不跳过继续）      │
   └────────────────────────────────────────────┘
   每步内层 done 时 chat_service 同步做一件事：
   flush 缓冲 → 切片本步文本 → 落库
   （role=assistant + extra.plan_step_index=N）
        │
        ▼
④ 收尾总结  _finalize()
   喂给 LLM：任务 + 带状态符号的步骤清单
            + 各步实际产出 + 中断说明（如有）
   → 生成最终总结（不是简单拼步骤文本）
        │  yield plan.completed {summary, interrupted}
        │  yield done {full_response=summary, usage_breakdown 聚合}
        ▼
⑤ 终态持久化 + 计量
   chat_service 写 plan_state 的 summary/interrupted
     → update_extra() 整体替换 extra.plan
   done 的 usage_breakdown → _record_usage()
     → agent_usage 表（真实 token/cost，不再归零）
   总结作为最终 assistant 消息落库
```

---

## 三、六个阶段逐段说明

### ① 外层规划（生成计划）

- 用单独一次 LLM 调用（`response_format=json_object`、低温度）把用户任务拆成结构化计划：标题 + 步骤列表。
- **兜底语义**：模型返回合法 JSON（哪怕是空 steps）就原样采用，空 steps 走"单步直答"路径；只有解析失败/异常才替换为默认 3 步（步骤文本取 query 前 80 字符）。这样模型的判断不会被代码掩盖。

### ② 计划骨架落库

- 前端一收到 `plan.created` 就能看到计划卡（初始全部 `[ ]`）。
- 后端建一条 `role=plan` 消息，`extra.plan` 存 `{title, steps, statuses}`——这是整个计划的**单一事实源**，之后每次状态变化都整体重写这个 JSON。

### ③ 逐步执行（核心）

每一步都是一次**完整的 ReAct 循环**（内层 `AgentEngine.run()`），不是一次简单问答：

- **上下文组装**：基础会话消息浅拷贝 + 一条"此前步骤产出"蒸馏块（每步产出取头 400 + 尾 1000 字符节选，中间省略可经 `plan_output` 工具回查全文）+ 本步 prompt。不共享完整列表的原因：步 2 若继承步 1 的全部工具原始流量，token 会爆炸；蒸馏块让预算线性可控。
- **实时可见**：内层的流式 token、工具调用、思考过程事件原样透传，聊天视图照常渲染。
- **iteration 全局化**：内层每步从 1 重计数，`chat_service` 在事件循环顶部加"已完成的步数偏移"后写回——落库与前端拿到的是同一个全局轮号，不会同号互相覆盖。
- **每步收尾（内层 done 事件）**：先 flush 流式缓冲，按起点切片出本步文本，落库为 `role=assistant` + `extra.plan_step_index=N` 的消息。**修复前这里被吞掉，步结论刷新即失；现在每步文本都在。**
- **成功与失败**：
  - 正常结束 → `completed`（`[✓]`），继续下一步。
  - 触发截断（达到迭代上限）/ 错误 / 上下文溢出 → `blocked`（`[!]`），发 `plan.step_failed`，**立即中断整个循环**（fail-fast——你定的决策：宁可不完整也不拿错误结果继续）。之后 `_finalize` 会基于已完成部分作答，并标注"计划在第 N 步被中断"。
- **溢出保护**：每步各享一次压缩重试（`compress_fn` 透传给内层）；压缩后仍溢出 → 本步 blocked。

#### 上下文组装实例：步 2 如何看到步 1（以实测 SaaS 定价任务为例）

以 6 步「SaaS 定价策略」计划中的步 1→步 2 为例，看蒸馏块的真实数据流：

**1. 步 1 内层 ReAct 产生约 2 万字符原始流量（这些不会被继承）：**

```
步1「市场调研：明确目标客户画像与付费意愿」内层实际发生的：
├─ assistant tool_call: search_web("中小企业 SaaS 定价 付费意愿 调研 2026")
├─ tool result: 8200 字符搜索结果（Tavily 返回的原始网页摘要）
├─ assistant tool_call: search_web("SaaS ARPU 流失率 行业基准")
├─ tool result: 6500 字符
├─ assistant 思考 + 分析文本： 2400 字符
└─ done 事件: full_response = 2800 字符的调研结论文本
```

**2. 蒸馏：先「选」再「双窗截断」，不是硬切 2 万到 1500**——内层中间工具流量（搜索结果、思考）整体丢弃，只保留内层 LLM 自己写的最终结论（`planning_flow.py` 的 `step_output = d.get("full_response", "")`），再对结论做**头 400 + 尾 1000 双窗截断**（`_bound_step_output`）：

```python
prior_outputs.append(
    f"步骤{i + 1}「{step}」结果：{self._bound_step_output(step_output)}"
)
```

双窗设计的理由（`full_response` 是整步多轮文本拼接，最终结论总在尾部）：

- **头窗 400**：保任务定位（步骤开头通常回扣目标，"我先检索中小企业定价数据…"）
- **尾窗 1000**：保结论（"结论：目标客户付费带 ¥49-99/席位"——历史版本 `[:1500]` 头部截断会把这段整个切掉，是已修复的头部偏置 bug）
- 切点对齐行边界（不切半行）；中间插显式省略标记 `[…已省略约 N 字符；需要本步骤完整内容时可调用 plan_output 工具…]`——截断必须可见（DeerFlow 原则）
- 短产出（≤1400）原样注入零损失

**3. 步 2 的消息列表组装**（`step_messages = list(messages)` 浅拷贝——内层引擎会对传入列表原地 append，不拷贝会把本步工具流量永久污染进基础列表）：

```
[system]  ← 基础会话继承
[user]    制定SaaS定价策略...        ← 基础会话继承（浅拷贝）
[user]    此前步骤产出（节选；完整内容可 plan_output 查询）：步骤1「...」结果：头…尾   ← 蒸馏块
[user]    用户任务 + 计划进度 + 本步指令                      ← 步骤 prompt
```

**4. token 账：完整继承是 O(N²)，蒸馏后是 O(N) 线性：**

| 步骤 | 若继承完整工具流量 | 蒸馏块方案 |
|------|------------------|-----------|
| 步 1 | 2 万字符 | 0（无前序） |
| 步 2 | 2万 + 1.8万 = 3.8 万 | ≤1400 + 省略标记 |
| 步 3 | ~5.5 万 | ≤2800 |
| 步 6（最后） | ~10 万字符 | ≤7000 |

完整继承到最后一步上下文里塞着前 5 步的全部搜索原文——大部分是与当前步无关的噪声；蒸馏后每步只多付 (N-1)×1400 字符，且内容是前序步骤的头尾节选，正是执行当前步需要的前提。

**5. 三个保证：**

- **失败步不产出**：`if step_output:` 保证被 blocked 的步（空 full_response）不会往 prior_outputs 塞空块。
- **总结与中间步骤同口径**：`_finalize` 喂的是同一份 prior_outputs——总结看到的各步产出与中间步骤看到的一致，不会出现「总结时冒出中间步骤从没见过的信息」的口径漂移。
- **节选有损但信息不丢**：各步产出已由 chat_service 全文落库（`role=assistant` + `extra.plan_step_index=N`），模型需要被省略的中间细节时，调用 `plan_output` 工具按步骤号回查全文（工具内部做会话归属校验 + offset/limit 分页；仅计划模式注入工具列表）。

### ④ 收尾总结（_finalize）

把「任务 + 带状态符号的步骤清单 + 各步实际产出 +（如中断）说明」喂给 LLM 生成最终总结。修复前只喂步骤标题，总结是空话；现在总结基于各步真实产出，最终气泡与落库的最终 assistant 消息都是这段总结。

### ⑤ 终态持久化 + 计量

- `plan.completed` 时把 `summary`、`interrupted` 写回 `extra.plan`（`update_extra` 整体替换，随会话事务统一提交）。
- 聚合的 usage（六键 breakdown）走 `_record_usage` 写 `agent_usage` 表——修复前这里拿不到 usage 直接 return，token 归零、cost 假数据。
- 注意语义变化：`iterations` 现在是**真实 ReAct 轮数之和**（原来冒充为"步骤数"）。

---

## 四、事件流协议（前后端契约）

| 事件 | 载荷要点 | 前端行为 |
|---|---|---|
| `plan.created` | title, steps, step_count | 建计划卡，statuses 全 `not_started` |
| `plan.step_started` | step_index, step | 该步变 `[→]` in_progress |
| `plan.step_completed` | step_index | 该步变 `[✓]` |
| `plan.step_failed` | step_index, reason(truncated/error/context_overflow) | 该步变 `[!]` blocked，卡片标"已中断" |
| `plan.completed` | summary, interrupted | 写入 summary；**中断时也发**（收尾≠全部成功） |

状态机：`not_started → in_progress → completed / blocked`。

---

## 五、结束之后：三个消费视角

1. **刷新回放（聊天视图）**：计划卡从落库 `extra.plan` 还原（title/steps/statuses/summary）；各步文本从 `plan_step_index` 消息还原。历史数据无 statuses 时统一兜底全 `[✓]` 不崩。
2. **下一轮对话（短期记忆）**：`role=plan` 消息转成 `<plan-context>` user 块进上下文——模型知道本会话之前定过什么计划、执行到哪；`notice`（纠偏提示）显式跳过不回放。
3. **轨迹视图**：计划以符号清单呈现，`[✓]/[→]/[!]` 判定表在 TrajectoryList 与 TrajectoryInspector 两处保持一致。

---

## 六、实测验证记录（2026-09-29）

真实 UI + 真实 LLM 全链路通过（PlanE2E 智能体，6 步 SaaS 定价研究任务）：

| 验证项 | 结果 |
|---|---|
| 创建对话框「计划模式」开关 | ✓ 随智能体创建生效 |
| 计划卡实时推进 | ✓ 1/6 → 6/6，`[→]` 逐步变 `[✓]`，tag 执行中→已完成 |
| 步骤结论文本落库 | ✓ 6 条 step#0..5 消息 |
| iteration 全局连续 | ✓ it=1→6 无碰撞 |
| 计划终态持久化 | ✓ statuses 全 completed + summary + interrupted=False |
| usage 真实聚合 | ✓ agent_usage 记录 29206 tokens |
| 总结落屏 | ✓ 完整 Markdown 报告 |
| 刷新后历史回放 | ✓ 计划卡从落库完整还原 |

---

## 七、当前边界（二期候选）

- **无动态重规划**：计划一生成步骤固定，模型执行中不能增删改步骤（PlanningTool 方案，设计文档 E7 后半段，你已确认留二期）。
- **fail-fast 即终点**：某步 blocked 后整轮终止，不会自动重试该步；重试方式是在同一会话里让模型继续（`<plan-context>` 会带上 blocked 状态）。
- **产出节选 + 工具回查**：跨步传递的产出每步取头 400 + 尾 1000 字符双窗节选（`_bound_step_output`），省略部分显式标注；被省略的中间内容不丢——chat_service 已把各步全文落库（`extra.plan_step_index`），模型经 `plan_output` 工具按步骤号回查（仅计划模式注入）。如需超大外部产物全文，仍推荐工具侧持久化（如知识库挂载）而非计划上下文。
